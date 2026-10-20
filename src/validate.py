"""Validation gate (arch §4.6): runs on the rendered note before anything leaves the machine."""
from __future__ import annotations

import re
from typing import Any, Dict, List

from .clean import pii

_WORD = re.compile(r"[A-Za-z0-9]")


def word_count(markdown: str) -> int:
    """Words a reader sees: tokens with at least one letter or digit (markup like ** or - ignored)."""
    return sum(1 for tok in markdown.split() if _WORD.search(tok))


def validate(note: Dict[str, Any], markdown: str, rows: Dict[str, Dict[str, Any]],
             themes: Dict[str, Any], max_words: int, max_themes: int, top_n: int = 3) -> List[str]:
    """Return a list of failed checks; empty means the note may be published."""
    failures = []

    words = word_count(markdown)
    if words > max_words:
        failures.append("length: %d words, limit is %d" % (words, max_words))

    counts = {k: len(note[k]) for k in ("themes", "quotes", "actions")}
    if any(n != top_n for n in counts.values()):
        failures.append("structure: need %d themes, quotes and actions, got %s" % (top_n, counts))
    if any(not t.get("summary") for t in note["themes"]):
        failures.append("structure: a theme has no summary")

    for q in note["quotes"]:
        source = rows.get(q["review_id"], {}).get("text", "")
        if source[q["start"]:q["end"]] != q["text"] or q["text"] not in source:
            failures.append("quote integrity: quote from %s is not an exact substring of its review" % q["review_id"])
        elif '"%s"' % q["text"] not in markdown:
            failures.append("quote integrity: quote from %s is not in the note verbatim" % q["review_id"])

    found = pii.find_pii(markdown)
    if found:
        failures.append("pii: found %s in the note" % ", ".join(found))

    if len(themes["themes"]) > max_themes:
        failures.append("theme cap: %d themes, limit is %d" % (len(themes["themes"]), max_themes))

    top_ids = {t["theme_id"] for t in themes["themes"] if t.get("top")}
    if any(a["theme_id"] not in top_ids for a in note["actions"]):
        failures.append("grounding: an action is tied to a theme outside the top %d" % top_n)
    if any(t["theme_id"] not in top_ids for t in note["themes"]):
        failures.append("grounding: the note shows a theme outside the top %d" % top_n)
    return failures
