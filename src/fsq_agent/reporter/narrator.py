"""Turn statistical findings into an executive summary (Sprint 3)."""

from fsq_agent.core.llm import LLMClient
from fsq_agent.reporter.pipeline import Finding

SYSTEM_PROMPT = """You write short executive data summaries for business leaders.

Rules:
- Use ONLY the numbers provided. Never invent or extrapolate figures.
- Plain business English, no jargon. 3-6 sentences plus bullets if needed.
- Lead with the most significant shift. Group related findings.
- If findings span multiple business units, call out the cross-unit angle.
"""


def narrate(findings: list[Finding]) -> str:
    if not findings:
        return "Nightly scan complete: no notable shifts detected across the feature store."
    bullets = "\n".join(f.as_bullet() for f in findings)
    llm = LLMClient()
    return llm.complete(
        SYSTEM_PROMPT,
        f"Today's detected shifts (already statistically validated):\n{bullets}\n\n"
        "Write the executive summary.",
    )
