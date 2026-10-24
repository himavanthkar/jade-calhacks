"""The model's only doorway. Claude drafts escalation questions and plays the humans; it never
computes a number and never posts. Everything here is optional: with TPA_USE_MODEL unset, or no
ANTHROPIC_API_KEY, every call returns None and the caller falls back to its deterministic path.

    TPA_USE_MODEL=1        turn the model on
    TPA_MODEL              model id, default claude-opus-5-5
"""

import json
import os
import re

DEFAULT_MODEL = "claude-opus-5-5"
NUMBER = re.compile(r"\$?\d[\d,]*(?:\.\d+)?%?")
ID = re.compile(r"\b[A-Z]{2,3}-\d{2,4}\b")


def enabled() -> bool:
    return os.environ.get("TPA_USE_MODEL") == "1" and bool(os.environ.get("ANTHROPIC_API_KEY"))


def ask(system: str, prompt: str, *, max_tokens: int = 800) -> str | None:
    if not enabled():
        return None
    try:
        import anthropic

        msg = anthropic.Anthropic().messages.create(
            model=os.environ.get("TPA_MODEL", DEFAULT_MODEL), max_tokens=max_tokens, system=system,
            messages=[{"role": "user", "content": prompt}])
        return "".join(b.text for b in msg.content if b.type == "text").strip() or None
    except Exception:          # the deterministic path is always there; a model outage never blocks the close
        return None


def ask_json(system: str, prompt: str, **kw) -> dict | None:
    text = ask(system, prompt + "\n\nReply with one JSON object and nothing else.", **kw)
    if not text:
        return None
    m = re.search(r"\{.*\}", text, re.S)
    try:
        return json.loads(m.group(0)) if m else None
    except json.JSONDecodeError:
        return None


def facts(text: str) -> set[str]:
    """The numbers and record ids in a text: what a rewrite must keep exactly."""
    return {n.lstrip("$").rstrip("%").replace(",", "") for n in NUMBER.findall(text)} | set(ID.findall(text))


def keeps_facts(original: str, rewrite: str) -> bool:
    return facts(original) <= facts(rewrite) and facts(rewrite) <= facts(original)
