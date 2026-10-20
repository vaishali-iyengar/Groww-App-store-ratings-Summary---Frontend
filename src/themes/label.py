"""Name each cluster: the LLM reads a sample and returns a short name and one-line description."""
from __future__ import annotations

from typing import Any, Callable, Dict, List

import numpy as np

# Areas that carry most of the volume and pain in real Groww reviews (plan §5.1). Suggested, not enforced.
HINTS = (
    "customer support", "performance and bugs", "charges and brokerage", "trading, charts and F&O",
    "UI and updates", "withdrawals and payments", "KYC and onboarding", "mutual funds and SIP",
    "fraud and losses",
)

# A labeller takes one sample per cluster and returns one {"name", "description"} per cluster, in order.
Sample = Dict[str, Any]
Labeller = Callable[[List[Sample]], List[Dict[str, str]]]


class LabelError(RuntimeError):
    pass


def stratified(indices: List[int], rows: List[Dict[str, Any]], size: int) -> List[int]:
    """Take `size` indices round-robin across star ratings, keeping each rating's own order."""
    by_rating: Dict[int, List[int]] = {}
    for i in indices:
        by_rating.setdefault(rows[i]["rating"], []).append(i)
    queues = [by_rating[r] for r in sorted(by_rating)]
    out: List[int] = []
    while len(out) < size and any(queues):
        for q in queues:
            if q and len(out) < size:
                out.append(q.pop(0))
    return out


def build_samples(
    rows: List[Dict[str, Any]], vectors: np.ndarray, labels: np.ndarray, centroids: np.ndarray, size: int
) -> List[Sample]:
    """Up to `size` reviews per cluster, closest to the centroid first, spread across star ratings
    so one rating does not set the name. Review text is already PII-masked."""
    samples = []
    for c, cent in enumerate(centroids):
        idx = np.flatnonzero(labels == c)
        nearest = idx[np.argsort(-(vectors[idx] @ cent), kind="stable")].tolist()
        picked = stratified(nearest, rows, size)
        samples.append({
            "cluster": c,
            "size": int(len(idx)),
            "reviews": [{"rating": rows[i]["rating"], "text": rows[i]["text"]} for i in picked],
        })
    return samples


SYSTEM = """You name themes in Google Play reviews of Groww, an Indian investing app. \
Each cluster below groups similar reviews; short generic praise has already been removed. For every cluster, return a short theme name \
(2 to 5 words, Title Case) and a one-line description (at most 20 words) of what those users \
are saying. Names must be distinct across clusters and describe the dominant topic, not the \
sentiment alone. Useful areas include %s, but only use one when it fits; otherwise name what \
you see. Reviews have personal details replaced with placeholders like [phone]; ignore them.""" % (
    ", ".join(HINTS)
)

SCHEMA = {
    "type": "object",
    "properties": {
        "themes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "cluster": {"type": "integer"},
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                },
                "required": ["cluster", "name", "description"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["themes"],
    "additionalProperties": False,
}


def _prompt(samples: List[Sample]) -> str:
    parts = []
    for s in samples:
        lines = "\n".join("- (%d stars) %s" % (r["rating"], r["text"]) for r in s["reviews"])
        parts.append("Cluster %d (%d reviews):\n%s" % (s["cluster"], s["size"], lines))
    return "\n\n".join(parts) + "\n\nReturn one theme per cluster."


def llm_labeller(provider: str, model: str) -> Labeller:
    from .. import llm

    try:
        complete = llm.client(provider, model)
    except llm.LLMError as exc:
        raise LabelError(str(exc))

    def label(samples: List[Sample]) -> List[Dict[str, str]]:
        try:
            out = complete(SYSTEM, _prompt(samples), SCHEMA, 4000)
        except llm.LLMError as exc:
            raise LabelError(str(exc))
        by_cluster = {t["cluster"]: t for t in out["themes"]}
        return [by_cluster.get(s["cluster"], {}) for s in samples]

    return label


def keyword_labeller(samples: List[Sample]) -> List[Dict[str, str]]:
    """Offline fallback (--no-llm): name each cluster by its most distinctive TF-IDF terms."""
    from sklearn.feature_extraction.text import TfidfVectorizer

    docs = [" ".join(r["text"] for r in s["reviews"]) for s in samples]
    tfidf = TfidfVectorizer(stop_words="english", token_pattern=r"(?u)\b[a-zA-Z]{3,}\b")
    weights = tfidf.fit_transform(docs).toarray()
    terms = tfidf.get_feature_names_out()
    out = []
    for row in weights:
        top = [terms[i] for i in np.argsort(-row, kind="stable")[:3]]
        out.append({"name": " / ".join(top).title(), "description": "Keywords: %s" % ", ".join(top)})
    return out


def label_clusters(samples: List[Sample], labeller: Labeller) -> List[Dict[str, str]]:
    labels = labeller(samples)
    if len(labels) != len(samples) or any(not (l.get("name") or "").strip() for l in labels):
        raise LabelError("labeller must return a non-empty name for every cluster")
    seen = set()
    out = []
    for l in labels:
        name = l["name"].strip()
        if name.lower() in seen:  # keep names unique so stats and week-over-week match cleanly
            name = "%s (%d)" % (name, len(seen) + 1)
        seen.add(name.lower())
        out.append({"name": name, "description": (l.get("description") or "").strip()})
    return out
