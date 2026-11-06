"""Shared, user-facing rendering of workflow context placeholders.

The core renderer has no dependency on the CLI, executor, or artifact layer.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def render_template(
    text: str,
    context: Mapping[str, Any],
    *,
    location: str | None = None,
) -> str:
    """Expand a workflow string and report missing/invalid placeholders consistently."""
    prefix = f"{location}: " if location else ""
    try:
        return text.format(**context)
    except KeyError as error:
        missing = error.args[0]
        raise ValueError(
            f"{prefix}Unknown context placeholder {{{missing}}} in {text!r}."
        ) from error
    except (ValueError, IndexError, AttributeError) as error:
        raise ValueError(f"{prefix}Invalid context template {text!r}: {error}") from error
