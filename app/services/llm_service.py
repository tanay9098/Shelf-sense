"""Optional, provider-independent LLM summariser.

The LLM never sees the database and never writes Cypher. It only rewrites the
deterministic summary from a structured evidence payload. Its output is validated:
every record ID it mentions must appear in the evidence, otherwise the deterministic
summary is used instead.

Providers (LLM_PROVIDER):
  none       - default; deterministic templates only
  anthropic  - Claude via the official `anthropic` SDK (requires ANTHROPIC_API_KEY)
Add a provider by implementing `Summariser.summarise`.
"""
from __future__ import annotations

import json
import logging
import re

from app.config import Settings, get_settings

log = logging.getLogger("shelfsense.llm")

ID_PATTERN = re.compile(r"\b(?:R|P|D|W|O|DEL|SV|PR|INV)-[A-Z0-9-]*\d\b")

SYSTEM_PROMPT = (
    "You are the reporting layer of a retail-availability investigation tool. You receive a JSON payload of "
    "records already retrieved from a graph database plus a rule-based conclusion. Write a 2-3 sentence "
    "plain-English summary for a distribution manager. Use only facts in the payload; do not add causes, "
    "numbers, dates, people or record IDs that are not present. Keep the stated confidence and status. "
    "If the status is 'undetermined', say the cause cannot be determined. Distinguish facts from inferences. "
    "Output the summary text only."
)


class Summariser:
    name = "deterministic"

    def summarise(self, payload: dict, fallback: str) -> tuple[str, str, str | None]:
        """Return (summary, source, note)."""
        return fallback, "deterministic", None


class AnthropicSummariser(Summariser):
    name = "anthropic"

    def __init__(self, settings: Settings):
        self.settings = settings

    def summarise(self, payload: dict, fallback: str) -> tuple[str, str, str | None]:
        try:
            import anthropic  # optional dependency
        except ImportError:
            return fallback, "deterministic", "anthropic package not installed"
        try:
            client = anthropic.Anthropic(timeout=float(self.settings.llm_timeout_seconds), max_retries=1)
            response = client.messages.create(
                model=self.settings.llm_model,
                max_tokens=1024,
                system=SYSTEM_PROMPT,
                output_config={"effort": "low"},
                messages=[{"role": "user", "content": json.dumps(payload, default=str)}],
            )
        except Exception as exc:  # network, auth, rate limit: never break the investigation
            log.warning("LLM summary failed: %s", type(exc).__name__)
            return fallback, "deterministic", f"LLM unavailable ({type(exc).__name__})"
        if getattr(response, "stop_reason", None) == "refusal":
            return fallback, "deterministic", "LLM declined; deterministic summary used"
        text = "".join(b.text for b in response.content if getattr(b, "type", "") == "text").strip()
        ok, reason = validate_summary(text, payload)
        if not ok:
            return fallback, "deterministic", f"LLM summary rejected: {reason}"
        return text, "llm", None


def allowed_ids(payload: dict) -> set[str]:
    return set(ID_PATTERN.findall(json.dumps(payload, default=str)))


def validate_summary(text: str, payload: dict) -> tuple[bool, str]:
    if not text:
        return False, "empty output"
    if len(text) > 1200:
        return False, "too long"
    unknown = set(ID_PATTERN.findall(text)) - allowed_ids(payload)
    if unknown:
        return False, f"mentions record IDs not in evidence: {sorted(unknown)}"
    if payload.get("probable_cause", {}).get("status") == "undetermined" and "cannot" not in text.lower():
        return False, "did not preserve the undetermined status"
    return True, "ok"


def get_summariser(settings: Settings | None = None) -> Summariser:
    s = settings or get_settings()
    if s.llm_provider == "anthropic" and s.llm_enabled:
        return AnthropicSummariser(s)
    return Summariser()
