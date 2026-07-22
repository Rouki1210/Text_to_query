"""Provider-agnostic LLM client.

Keeping this behind one interface means the model/provider choice
(a deliverable of this internship) can change without touching the rest
of the codebase.
"""

from anthropic import Anthropic

from fsq_agent.config import settings


class LLMError(RuntimeError):
    """The model returned a response we can't extract SQL from."""


class LLMClient:
    def __init__(self) -> None:
        # base_url is optional: only pass it when configured, so the SDK
        # falls back to its own default endpoint otherwise.
        kwargs = {
            "api_key": settings.anthropic_api_key,
            "max_retries": settings.llm_max_retries,
        }
        if settings.llm_base_url:
            kwargs["base_url"] = settings.llm_base_url
        self._client = Anthropic(**kwargs)
        self._model = settings.llm_model

    def complete(self, system: str, user: str, max_tokens: int | None = None) -> str:
        """Single-turn completion. Returns raw text."""
        response = self._client.messages.create(
            model=self._model,
            max_tokens=max_tokens or settings.llm_max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        # content is a list of blocks; thinking-capable models put a
        # ThinkingBlock first, so pick the first text block rather than [0].
        text = "".join(b.text for b in response.content if b.type == "text")
        if not text:
            blocks = [b.type for b in response.content]
            hint = (
                " The budget was spent on thinking before any answer was written"
                " — raise LLM_MAX_TOKENS."
                if response.stop_reason == "max_tokens"
                else ""
            )
            raise LLMError(
                f"no text block in response (stop_reason={response.stop_reason}, "
                f"blocks={blocks}).{hint}"
            )
        return text
