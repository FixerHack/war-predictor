"""Text normalisation and change detection between advisory versions."""

import difflib
import re

_WS = re.compile(r"[ \t ]+")


# Service lines that change on every re-publication without any change in substance.
# Only lines whose remainder is date-like are dropped ("Updated: ordered departure" stays).
_DATE = r"[\w ,./:-]{0,25}\d{2,4}[\w ,./:-]{0,15}"
_BOILERPLATE = [
    re.compile(p, re.I)
    for p in (
        rf"^(last |latest )?(updated|reviewed)( on)?:? {_DATE}$",
        rf"^still current at:? {_DATE}$",
        rf"^(date|published|issued)( on)?:? {_DATE}$",
        rf"^(stand|letzte änderung|mise à jour)( le| am)?:? {_DATE}$",
        rf"^(unverändert )?gültig seit:? {_DATE}$",
        r"^\d{1,2}[./ ]\w+[./ ]\d{2,4}$",  # a bare date
        # US State Department reissue notes (the level itself is compared separately)
        r"^there were no changes to the advisory level or risk indicators\b.{0,80}$",
        r"^reissued (after|with) .{0,80}$",
        r"^advisory summary:?$",
    )
]


def normalize(text: str) -> str:
    """Collapse whitespace, drop empty lines and boilerplate (update dates), so cosmetic
    edits don't count as changes."""
    lines = (_WS.sub(" ", line).strip() for line in text.splitlines())
    return "\n".join(
        line for line in lines if line and not any(p.match(line) for p in _BOILERPLATE)
    )


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
