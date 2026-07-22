"""Nightly trend detection (Sprint 3).

Design principle: statistics find the shifts, the LLM only narrates them.
The LLM never touches raw data, which keeps numbers hallucination-free.
"""

from dataclasses import dataclass
from datetime import date

import pandas as pd

from fsq_agent.config import settings
from fsq_agent.sql.executor import execute_readonly

# Metrics the nightly scan watches. Add a row here to monitor a new metric.
WATCHED_METRICS = [
    {
        "name": "EV units sold",
        "unit": "electric_vehicles",
        "sql": """SELECT snapshot_date AS d, region || ' / ' || model AS dim,
                         SUM(units_sold) AS value
                  FROM ev_sales_daily GROUP BY 1, 2""",
    },
    {
        "name": "Real estate avg asking price",
        "unit": "real_estate",
        "sql": """SELECT snapshot_date AS d, region AS dim,
                         AVG(asking_price) AS value
                  FROM re_listings_daily GROUP BY 1, 2""",
    },
]


@dataclass
class Finding:
    metric: str
    dimension: str
    latest_value: float
    baseline_mean: float
    pct_change: float
    zscore: float

    def as_bullet(self) -> str:
        direction = "up" if self.pct_change > 0 else "down"
        return (
            f"{self.metric} [{self.dimension}]: {direction} "
            f"{abs(self.pct_change):.0%} vs 28-day baseline "
            f"(latest={self.latest_value:,.1f}, baseline={self.baseline_mean:,.1f}, "
            f"z={self.zscore:.1f})"
        )


def detect(as_of: date | None = None) -> list[Finding]:
    findings: list[Finding] = []
    for metric in WATCHED_METRICS:
        df = execute_readonly(metric["sql"])
        df["d"] = pd.to_datetime(df["d"])
        latest_day = df["d"].max() if as_of is None else pd.Timestamp(as_of)

        for dim, grp in df.groupby("dim"):
            grp = grp.sort_values("d")
            baseline = grp[grp["d"] < latest_day].tail(28)["value"]
            latest = grp[grp["d"] == latest_day]["value"]
            if len(baseline) < 7 or latest.empty or baseline.std() == 0:
                continue

            latest_value = float(latest.iloc[0])
            z = (latest_value - baseline.mean()) / baseline.std()
            pct = (latest_value - baseline.mean()) / abs(baseline.mean())

            if abs(z) >= settings.zscore_threshold and abs(pct) >= settings.min_pct_change:
                findings.append(Finding(
                    metric=metric["name"], dimension=str(dim),
                    latest_value=latest_value, baseline_mean=float(baseline.mean()),
                    pct_change=float(pct), zscore=float(z),
                ))

    return sorted(findings, key=lambda f: abs(f.zscore), reverse=True)
