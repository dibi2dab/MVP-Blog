"""Crystal / Quartz editorial pipeline.

Obsidian (eneru.tistory.com) is intentionally not part of this package. It keeps
using the existing stock pipeline in ``main.py`` and ``src/pipeline``.

This package adds a separate, evidence-first editorial workflow for:

- Crystal  (rumbell)  — online income / practical profitability (CPPI)
- Quartz   (quar1z)   — AI, software, digital products (QDVI)
"""

from src.editorial.profiles import BlogProfile, get_profile, list_profiles

__all__ = ["BlogProfile", "get_profile", "list_profiles"]
