"""Pulse writer (arch §4.5): the LLM drafts the headline, 3 summaries and 3 actions. It never writes quotes."""
from __future__ import annotations

import json
from typing import Any, Callable, Dict, List, Optional

OWNERS = ("Product", "Support", "Growth")

# writer(context, feedback) -> {"headline", "summaries": [{theme_id, summary}], "actions": [{theme_id, action, owner}]}
Writer = Callable[[Dict[str, Any], Optional[List[str]]], Dict[str, Any]]


class WriterError(RuntimeError):
    pass


def build_context(themes: Dict[str, Any], top: List[Dict[str, Any]], pools: Dict[str, List[Dict[str, Any]]],
                  previous_top: Optional[List[str]]) -> Dict[str, Any]:
    """Only the numbers and text the writer may use."""
    total = themes["review_count"]
    return {
        "week_of": themes.get("week_of"),
        "review_count": total,
        "low_confidence": themes["low_confidence"],
        "top_themes": [
            {
                "theme_id": t["theme_id"], "name": t["name"], "description": t["description"],
                "share_of_reviews_pct": round(100 * t["review_count"] / total),
                "avg_rating": t["avg_rating"],
                "week_over_week_share_change_pts": (
                    round(100 * t["wow_share_change"], 1) if t.get("wow_share_change") is not None else None
                ),
            }
            for t in top
        ],
        "quote_candidates": {
            theme_id: [{"n": i, "rating": c["rating"], "text": c["text"]} for i, c in enumerate(pool, 1)]
            for theme_id, pool in pools.items()
        },
        "last_weeks_top_themes": previous_top,
    }


SYSTEM = """You write a one-page weekly pulse of Google Play reviews of Groww, an Indian \
investing app, for product, support and growth leads. Use only the numbers in the input; \
never invent statistics, quotes or user names. Return:
- headline: one line, at most 14 words, naming the main pain this week;
- summaries: one per theme_id, at most 16 words each, saying what users report (no numbers; \
the renderer adds share and rating);
- actions: exactly 3, each tied to one of the given theme_ids (one per theme), at most 16 words, \
concrete and doable within a sprint, with an owner chosen by what the action changes:
  Product = the app itself: features, charts, UI, bugs, crashes, performance, updates;
  Support = handling users: customer service, response times, withdrawal, KYC and account cases;
  Growth = pricing, brokerage and fees, plans, onboarding funnels, acquisition and retention;
- quote_choices: for each theme_id, the number n of the candidate quote that best shows that \
theme's own topic. Skip candidates that are about a different topic than the theme.
Do not write or edit quotes; the chosen candidates are inserted verbatim. Keep the whole note brief: it must stay \
under 250 words including quotes."""

SCHEMA = {
    "type": "object",
    "properties": {
        "headline": {"type": "string"},
        "summaries": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"theme_id": {"type": "string"}, "summary": {"type": "string"}},
                "required": ["theme_id", "summary"],
                "additionalProperties": False,
            },
        },
        "quote_choices": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"theme_id": {"type": "string"}, "candidate": {"type": "integer"}},
                "required": ["theme_id", "candidate"],
                "additionalProperties": False,
            },
        },
        "actions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "theme_id": {"type": "string"},
                    "action": {"type": "string"},
                    "owner": {"type": "string", "enum": list(OWNERS)},
                },
                "required": ["theme_id", "action", "owner"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["headline", "summaries", "quote_choices", "actions"],
    "additionalProperties": False,
}


def llm_writer(provider: str, model: str) -> Writer:
    from .. import llm

    try:
        complete = llm.client(provider, model, effort="medium")
    except llm.LLMError as exc:
        raise WriterError(str(exc))

    def write(context: Dict[str, Any], feedback: Optional[List[str]] = None) -> Dict[str, Any]:
        prompt = "Input:\n" + json.dumps(context, indent=2, ensure_ascii=False)
        if feedback:
            prompt += "\n\nYour previous draft failed these checks; fix them:\n- " + "\n- ".join(feedback)
        try:
            return complete(SYSTEM, prompt, SCHEMA, 4000)
        except llm.LLMError as exc:
            raise WriterError(str(exc))

    return write


# Same owner rules as the prompt, by keyword; first match wins.
_OWNER_HINTS = (
    ("support", "Support"), ("care", "Support"), ("withdraw", "Support"), ("kyc", "Support"),
    ("account", "Support"), ("charge", "Growth"), ("brokerage", "Growth"), ("fee", "Growth"),
    ("pricing", "Growth"),
)


def _trim(text: str, words: int) -> str:
    parts = text.split()
    return text if len(parts) <= words else " ".join(parts[:words]).rstrip(",;:") + "…"


def template_writer(context: Dict[str, Any], feedback: Optional[List[str]] = None) -> Dict[str, Any]:
    """Offline fallback (--no-llm): plain wording built from the theme names and descriptions."""
    top = context["top_themes"]

    def owner(t: Dict[str, Any]) -> str:
        # Name only: descriptions mention side topics ("...and high brokerage") that mislead.
        name = t["name"].lower()
        return next((o for k, o in _OWNER_HINTS if k in name), "Product")

    return {
        "headline": "%s leads this week's feedback." % top[0]["name"],
        "summaries": [{"theme_id": t["theme_id"], "summary": _trim(t["description"] or t["name"], 14)} for t in top],
        "quote_choices": [{"theme_id": t["theme_id"], "candidate": 1} for t in top],
        "actions": [
            {"theme_id": t["theme_id"], "owner": owner(t),
             "action": "Agree one fix for the top %s complaints next sprint." % t["name"]}
            for t in top
        ],
    }
