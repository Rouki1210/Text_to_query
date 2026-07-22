"""Entrypoint for the scheduled nightly report.

Schedule with cron:
    0 6 * * 1-5  cd /path/to/fsq-agent && .venv/bin/python scripts/run_nightly.py
or with APScheduler if you prefer keeping it inside Python.
"""

from fsq_agent.reporter.narrator import narrate
from fsq_agent.reporter.pipeline import detect
from fsq_agent.reporter.publisher import publish


def main() -> None:
    findings = detect()
    summary = narrate(findings)
    publish(summary)


if __name__ == "__main__":
    main()
