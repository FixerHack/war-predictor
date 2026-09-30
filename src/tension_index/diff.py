"""Text normalisation and change detection between advisory versions."""

import difflib
import re

_WS = re.compile(r"[ \t ]+")


def normalize(text: str) -> str:
    """Collapse whitespace and drop empty lines so cosmetic edits don't count as changes."""
    lines = (_WS.sub(" ", line).strip() for line in text.splitlines())
    return "\n".join(line for line in lines if line)


def changed_fragment(old: str, new: str, context: int = 1) -> str:
    """Return a compact unified diff of `old` -> `new` (empty string if identical).

    Only the diff (not the whole advisory) is later sent to the LLM classifier,
    which keeps API costs low.
    """
    old_n, new_n = normalize(old), normalize(new)
    if old_n == new_n:
        return ""
    lines = difflib.unified_diff(old_n.splitlines(), new_n.splitlines(), lineterm="", n=context)
    # Skip the '---' / '+++' header lines.
    return "\n".join(line for line in lines if not line.startswith(("---", "+++")))
