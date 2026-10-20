"""Assemble the note in the architecture §4.5.1 layout. Quotes are inserted verbatim by code."""
from __future__ import annotations

from datetime import date
from typing import Any, Dict, List

from .quotes import choose
from .writer import WriterError


def _day(d: str) -> str:
    return date.fromisoformat(d[:10]).strftime("%-d %b %Y")


def build_note(context: Dict[str, Any], fields: Dict[str, Any], pools: Dict[str, List[Dict[str, Any]]],
               window: Dict[str, str]) -> Dict[str, Any]:
    """Join the writer's fields to the top themes by theme_id, in rank order. Quotes come from the
    candidate pools by the writer's numbered choice, never from the writer's own text."""
    choices = {c["theme_id"]: c["candidate"] for c in fields.get("quote_choices", [])}
    quotes = choose(pools, choices, len(context["top_themes"]))
    summaries = {s["theme_id"]: s["summary"].strip() for s in fields.get("summaries", [])}
    names = {t["theme_id"]: t["name"] for t in context["top_themes"]}
    if not isinstance(fields.get("headline"), str):
        raise WriterError("writer returned no headline")
    return {
        "week_of": context["week_of"],
        "window": window,
        "review_count": context["review_count"],
        "low_confidence": context["low_confidence"],
        "headline": fields["headline"].strip(),
        "themes": [dict(t, summary=summaries.get(t["theme_id"], "")) for t in context["top_themes"]],
        "quotes": [{k: q[k] for k in ("theme_id", "theme", "review_id", "rating", "start", "end", "text")}
                   for q in quotes],
        "actions": [
            {"theme_id": a["theme_id"], "theme": names.get(a["theme_id"]), "action": a["action"].strip(),
             "owner": a["owner"]}
            for a in fields.get("actions", [])
        ],
    }


def render(note: Dict[str, Any], plain: bool = False) -> str:
    """Markdown for pulse.md, or plain text (plain=True) for Google Docs and email, where
    Markdown is not interpreted. Both come from this one layout so they cannot drift apart."""
    bold = (lambda x: x) if plain else (lambda x: "**%s**" % x)
    italic = (lambda x: x) if plain else (lambda x: "*%s*" % x)

    lines = [bold("Groww Weekly Review Pulse: week of %s" % _day(note["week_of"])), italic(note["headline"]), ""]
    if note["low_confidence"]:
        lines += [italic("Low confidence: only %d reviews in the window." % note["review_count"]), ""]

    lines.append(bold("Top themes"))
    for i, t in enumerate(note["themes"], 1):
        stats = "%d%% of reviews, ★%.1f" % (t["share_of_reviews_pct"], t["avg_rating"])
        change = t.get("week_over_week_share_change_pts")
        if change:
            stats += ", %s%g pts vs last week" % ("+" if change > 0 else "", change)
        lines.append("%d. %s (%s): %s" % (i, bold(t["name"]), stats, t["summary"]))
    lines.append("")

    lines.append(bold("What users said"))
    rank_of = {t["theme_id"]: i for i, t in enumerate(note["themes"], 1)}
    for q in note["quotes"]:  # label by theme number: repeating long theme names costs ~15 words
        lines.append('- "%s" (★%d, theme %d)' % (q["text"], q["rating"], rank_of[q["theme_id"]]))
    lines.append("")

    lines.append(bold("Action ideas"))
    for i, a in enumerate(note["actions"], 1):
        lines.append("%d. %s (%s)" % (i, a["action"].rstrip("."), a["owner"]))
    lines.append("")

    w = note["window"]
    lines.append(italic("Based on %d public Play Store reviews, %s to %s." % (
        note["review_count"], _day(w["start"]), _day(w["end"]))))
    return "\n".join(lines) + "\n"


def email_body(plain_note: str, doc_url: str) -> str:
    """The same plain-text note as the Doc, followed by the Doc link."""
    return "%s\nGoogle Doc: %s\n" % (plain_note, doc_url)


def day_label(week_of: str) -> str:
    return _day(week_of)
