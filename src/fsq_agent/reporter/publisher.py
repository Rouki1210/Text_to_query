"""Publish the executive summary to the team channel."""

import requests

from fsq_agent.config import settings


def publish(summary: str) -> None:
    if not settings.slack_webhook_url:
        print("[dry-run] SLACK_WEBHOOK_URL not set. Summary:\n")
        print(summary)
        return
    resp = requests.post(
        settings.slack_webhook_url,
        json={"text": f":bar_chart: *Nightly Feature Store Report*\n\n{summary}"},
        timeout=10,
    )
    resp.raise_for_status()
