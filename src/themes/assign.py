"""LLM theming path (plan §5.2 decision point): the LLM proposes <=N themes, then assigns every review."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Callable, Dict, List, Optional, Tuple

from .label import HINTS, LabelError
from .rank import Group

SAMPLE_SIZE = 150
BATCH_SIZE = 50  # keeps each call well inside Groq free-tier tokens per minute
CONFIDENCE = {"high": 1.0, "medium": 0.66, "low": 0.33}

# proposer(sample reviews, max themes) -> [{"name", "description"}]
Proposer = Callable[[List[Dict[str, Any]], int], List[Dict[str, str]]]
# assigner(themes, batch of reviews) -> [{"review_id", "theme" (1-based, 0 = Other), "confidence"}]
Assigner = Callable[[List[Dict[str, str]], List[Dict[str, Any]]], List[Dict[str, Any]]]


def stratified_sample(rows: List[Dict[str, Any]], size: int = SAMPLE_SIZE) -> List[Dict[str, Any]]:
    """Round-robin across (rating, week) buckets so no rating or week dominates the proposal."""
    buckets: Dict[Tuple[int, date], List[Dict[str, Any]]] = {}
    for r in rows:
        d = date.fromisoformat(r["date"][:10])
        buckets.setdefault((r["rating"], d - timedelta(days=d.weekday())), []).append(r)
    queues = [list(buckets[k]) for k in sorted(buckets)]
    out: List[Dict[str, Any]] = []
    while len(out) < size and any(queues):
        for q in queues:
            if q and len(out) < size:
                out.append(q.pop(0))
    return out


PROPOSE_SYSTEM = """You find themes in Google Play reviews of Groww, an Indian investing app. \
Read the sample and propose at most {n} themes that together cover most reviews. Each theme \
gets a short name (2 to 5 words, Title Case) and a one-line description (at most 20 words). \
Themes must be distinct, about a concrete topic rather than sentiment alone, and broad enough \
that each would hold at least 3% of reviews. Useful areas include {hints}, but only use one \
when the sample supports it. Reviews not fitting any theme will go to "Other", so do not \
propose an "Other" theme. Personal details are replaced with placeholders like [phone]; ignore them."""

ASSIGN_SYSTEM = """You assign Google Play reviews of Groww to themes. For each review, return \
the number of the single theme it is mainly about, or 0 if none fits, plus your confidence \
(high, medium or low). Return one entry for every review id."""

PROPOSE_SCHEMA = {
    "type": "object",
    "properties": {
        "themes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"name": {"type": "string"}, "description": {"type": "string"}},
                "required": ["name", "description"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["themes"],
    "additionalProperties": False,
}

ASSIGN_SCHEMA = {
    "type": "object",
    "properties": {
        "assignments": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "theme": {"type": "integer"},
                    "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
                },
                "required": ["id", "theme", "confidence"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["assignments"],
    "additionalProperties": False,
}


def _complete(provider: str, model: str):
    from .. import llm

    try:
        complete = llm.client(provider, model)
    except llm.LLMError as exc:
        raise LabelError(str(exc))

    def call(system: str, prompt: str, schema: Dict[str, Any], max_tokens: int) -> Dict[str, Any]:
        try:
            return complete(system, prompt, schema, max_tokens)
        except llm.LLMError as exc:
            raise LabelError(str(exc))

    return call


def llm_proposer(provider: str, model: str) -> Proposer:
    call = _complete(provider, model)

    def propose(sample: List[Dict[str, Any]], n: int) -> List[Dict[str, str]]:
        lines = "\n".join("- (%d stars) %s" % (r["rating"], r["text"]) for r in sample)
        system = PROPOSE_SYSTEM.format(n=n, hints=", ".join(HINTS))
        prompt = "Sample of %d reviews:\n%s\n\nPropose at most %d themes." % (len(sample), lines, n)
        return call(system, prompt, PROPOSE_SCHEMA, 4000)["themes"]

    return propose


def llm_assigner(provider: str, model: str) -> Assigner:
    call = _complete(provider, model)

    def assign(themes: List[Dict[str, str]], batch: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        listing = "\n".join("%d. %s: %s" % (i, t["name"], t["description"]) for i, t in enumerate(themes, 1))
        local = {"r%d" % i: r["review_id"] for i, r in enumerate(batch, 1)}  # short ids save tokens
        lines = "\n".join("%s: (%d stars) %s" % (k, r["rating"], r["text"]) for k, r in zip(local, batch))
        prompt = "Themes:\n%s\n0. Other: none of the above\n\nReviews:\n%s" % (listing, lines)
        out = call(ASSIGN_SYSTEM, prompt, ASSIGN_SCHEMA, 6000)["assignments"]
        return [dict(a, review_id=local[a["id"]]) for a in out if a["id"] in local]

    return assign


def llm_groups(
    rows: List[Dict[str, Any]], max_themes: int, proposer: Proposer, assigner: Assigner,
    progress: Optional[Callable[[int, int], None]] = None,
) -> Tuple[List[Group], List[Dict[str, str]], int]:
    """Return (groups ordered by size desc, their names, count of reviews left in Other)."""
    proposed = proposer(stratified_sample(rows), max_themes)[:max_themes]
    if not proposed or any(not (t.get("name") or "").strip() for t in proposed):
        raise LabelError("theme proposal returned no usable themes")
    themes = [{"name": t["name"].strip(), "description": (t.get("description") or "").strip()} for t in proposed]

    picked: Dict[str, Tuple[int, float]] = {}
    batches = (len(rows) + BATCH_SIZE - 1) // BATCH_SIZE
    for n, start in enumerate(range(0, len(rows), BATCH_SIZE), 1):
        if progress:
            progress(n, batches)
        for a in assigner(themes, rows[start:start + BATCH_SIZE]):
            if 1 <= a["theme"] <= len(themes):
                picked[a["review_id"]] = (a["theme"] - 1, CONFIDENCE.get(a["confidence"], 0.33))

    members: List[Group] = [[] for _ in themes]
    for i, r in enumerate(rows):
        if r["review_id"] in picked:
            t, conf = picked[r["review_id"]]
            members[t].append((i, conf))
    for g in members:
        g.sort(key=lambda m: -m[1])  # stable: equal confidence keeps file order
    order = sorted((k for k in range(len(themes)) if members[k]), key=lambda k: (-len(members[k]), k))
    other = len(rows) - len(picked)
    return [members[k] for k in order], [themes[k] for k in order], other
