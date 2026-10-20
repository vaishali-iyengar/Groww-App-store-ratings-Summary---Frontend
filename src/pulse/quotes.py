"""Pick verbatim quotes for the top themes, stored as review_id plus character offsets (arch §4.4)."""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from ..clean import pii
from ..themes.praise import _TOPIC

MAX_WORDS = 25
MIN_WORDS = 6
CANDIDATES = 40  # how far down each theme's member list to look

_SENTENCE = re.compile(r"[^.!?]+[.!?]*")
_PLACEHOLDER = re.compile(r"\[(?:email|phone|id|link|name)\]")
# Capitalised word pairs that are not product words: likely a person's name the masker missed.
_NAME_PAIR = re.compile(r"\b([A-Z][a-z]{2,})\s+([A-Z][a-z]{2,})\b")
_NOT_NAMES = {
    "groww", "app", "india", "indian", "google", "play", "store", "mutual", "fund", "funds", "stock",
    "stocks", "market", "customer", "care", "support", "team", "please", "very", "the", "this", "worst",
    "best", "good", "great", "trading", "view", "tradingview", "zerodha", "upstox", "angel", "one",
    "dear", "hello", "sir", "bad", "nice", "super", "user", "friendly", "experience", "service", "ipo",
}


def _spans(text: str) -> List[Tuple[int, int]]:
    """Sentence spans with surrounding whitespace trimmed."""
    spans = []
    for m in _SENTENCE.finditer(text):
        start, end = m.start(), m.end()
        while start < end and text[start].isspace():
            start += 1
        while end > start and text[end - 1].isspace():
            end -= 1
        if start < end:
            spans.append((start, end))
    return spans


def _words(text: str) -> int:
    return len(text.split())


def _clip(text: str, start: int, end: int, max_words: int) -> Tuple[int, int]:
    """Shorten [start, end) to its first max_words words, ending on a word boundary."""
    count = 0
    for m in re.finditer(r"\S+", text[start:end]):
        count += 1
        if count == max_words:
            return start, start + m.end()
    return start, end


def best_snippet(text: str, max_words: int = MAX_WORDS) -> Tuple[int, int]:
    """The contiguous run of whole sentences with the most topic terms that fits in max_words.

    A single sentence longer than max_words is clipped to its opening words, but only when no
    whole sentence fits.
    """
    if _words(text) <= max_words:
        return 0, len(text)
    spans = _spans(text) or [(0, len(text))]
    best: Optional[Tuple[int, int, int]] = None  # (score, start, end); clipped spans score -100
    for i in range(len(spans)):
        for j in range(i, len(spans)):
            start, end = spans[i][0], spans[j][1]
            clipped = False
            if _words(text[start:end]) > max_words:
                if i == j:  # one long sentence: keep its opening words
                    start, end = _clip(text, start, end, max_words)
                    clipped = True
                else:
                    break
            score = len(_TOPIC.findall(text[start:end])) - (100 if clipped else 0)
            if best is None or score > best[0]:
                best = (score, start, end)
    return best[1], best[2]


def looks_safe(snippet: str) -> bool:
    """No PII, no masked placeholders and no capitalised pair that looks like a person's name."""
    if pii.find_pii(snippet) or _PLACEHOLDER.search(snippet):
        return False
    for a, b in _NAME_PAIR.findall(snippet):
        if a.lower() not in _NOT_NAMES and b.lower() not in _NOT_NAMES:
            return False
    return True


def specificity(snippet: str) -> int:
    """Topic terms plus a point for any number: concrete complaints beat 'worst app ever'."""
    return min(len(_TOPIC.findall(snippet)), 3) + (1 if re.search(r"\d", snippet) else 0)


def candidates(theme: Dict[str, Any], rows: Dict[str, Dict[str, Any]], max_words: int) -> List[Dict[str, Any]]:
    out = []
    for pos, member in enumerate(theme["members"][:CANDIDATES]):
        row = rows[member["review_id"]]
        start, end = best_snippet(row["text"], max_words)
        snippet = row["text"][start:end]
        whole = end == len(row["text"].rstrip()) or snippet.rstrip()[-1:] in ".!?"
        if _words(snippet) < MIN_WORDS or not looks_safe(snippet):
            continue
        out.append({
            "theme_id": theme["theme_id"], "theme": theme["name"], "review_id": row["review_id"],
            "rating": row["rating"], "start": start, "end": end, "text": snippet,
            # complete sentences first, then most specific, then closest to the centre
            "_key": (0 if whole else 1, -specificity(snippet), pos),
        })
    out.sort(key=lambda c: c["_key"])
    for c in out:
        del c["_key"]
    return out


PER_THEME = 5  # candidates offered to the writer per theme


def candidate_pools(
    top: List[Dict[str, Any]], rows: Dict[str, Dict[str, Any]], per_theme: int = PER_THEME,
    max_words: int = MAX_WORDS,
) -> Dict[str, List[Dict[str, Any]]]:
    """Safe, verbatim candidates for each top theme, best first."""
    return {t["theme_id"]: candidates(t, rows, max_words)[:per_theme] for t in top}


def choose(pools: Dict[str, List[Dict[str, Any]]], choices: Dict[str, int], count: int = 3) -> List[Dict[str, Any]]:
    """One quote per theme: the writer's 1-based pick when valid, else the best-ranked candidate.

    The writer only names a number; the quote itself always comes from the pool, so it stays verbatim.
    Themes with no candidates are filled from the other themes' spare candidates.
    """
    chosen: List[Dict[str, Any]] = []
    spare: List[Dict[str, Any]] = []
    for theme_id, pool in pools.items():
        if not pool:
            continue
        pick = choices.get(theme_id, 1)
        idx = pick - 1 if isinstance(pick, int) and 1 <= pick <= len(pool) else 0
        chosen.append(pool[idx])
        spare += [c for i, c in enumerate(pool) if i != idx]
    while len(chosen) < count and spare:
        chosen.append(spare.pop(0))
    return chosen[:count]


def pick_quotes(
    top: List[Dict[str, Any]], rows: Dict[str, Dict[str, Any]], count: int = 3, max_words: int = MAX_WORDS,
) -> List[Dict[str, Any]]:
    """Best-ranked quote per theme without asking the writer."""
    return choose(candidate_pools(top, rows, max_words=max_words), {}, count)


def quote_text(quote: Dict[str, Any], rows: Dict[str, Dict[str, Any]]) -> str:
    """Re-read the quote from the clean review by its offsets."""
    return rows[quote["review_id"]]["text"][quote["start"]:quote["end"]]
