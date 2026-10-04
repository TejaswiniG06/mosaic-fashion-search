"""Shared prompt builders."""
from __future__ import annotations

from .schemas import Intent


def clip_prompt_for(intent: Intent | None) -> str | None:
    """English visual description for the CLIP text tower, built from normalised intent slots
    (works for Tamil/Hindi queries because slots are canonical English values)."""
    if not intent:
        return None
    parts = intent.colour[:1] + intent.pattern[:1] + intent.material[:1] + [c.replace("-", " ") for c in intent.category[:1]]
    return " ".join(parts) if parts else None
