"""Normalization, length filter, language tagging and de-duplication."""
from __future__ import annotations

import hashlib
import re
import unicodedata
from typing import Any, Dict, Iterable, List, Set, Tuple

_WS = re.compile(r"\s+")
_LETTER = re.compile(r"[^\W\d_]", re.UNICODE)


def normalize_text(text: str) -> str:
    """Unicode NFKC, strip control characters, collapse whitespace."""
    text = unicodedata.normalize("NFKC", text or "")
    text = "".join(ch for ch in text if ch in "\n\t" or unicodedata.category(ch)[0] != "C")
    return _WS.sub(" ", text).strip()


def word_count(text: str) -> int:
    return len(text.split())


# Romanised-Hindi words that are not English words. Ambiguous ones (to, me, is, hi, ho,
# na, tab, par) are left out on purpose.
_HINDI_MARKERS = frozenset("""
hai hain nahi nahin nhi bahut bohot bhot kya kyu kyun mein mei aur bhi koi raha rahi rahe
karo kare kiya kiye kar ke ki ka ko se ye yeh wo woh tha thi hua hui hoga hota hoti abhi
lekin magar paisa paise paisha accha acha achha bakwas bekar bhai mera meri mujhe tum aap
apna apni sab sabse kab kaise kyunki isliye wala wali liye lagta chahiye milta dena diya
gaya gayi wahi yahi bilkul sirf bas zyada jyada thoda kuch kaam ghatiya faltu dhokha nikal
bahot krta krti krna krte kro krke h sb inse usse unka inka uska iska rupya rupaye banaen
fayda pura chhote karwaye karwana hamesha dikkat samajh pata batao bata bataya rakha rakho
""".split())
_WORD = re.compile(r"[a-z]+")


def hindi_marker_count(text: str) -> int:
    return sum(1 for w in _WORD.findall(text.lower()) if w in _HINDI_MARKERS)


MAX_OTHER_SCRIPT_LETTERS = 3  # more than this many Devanagari, Bengali, ... letters means not English


def _is_latin(ch: str) -> bool:
    return unicodedata.name(ch, "").startswith("LATIN")  # includes accented letters such as è


def tag_language(text: str) -> str:
    """'en' (English), 'hinglish' (romanised Hindi / mixed) or 'other' (non-Latin script).

    Mixed-script reviews ("Groww App এ কি ...") count as 'other' once they hold more than a
    few non-Latin letters, so foreign-script text cannot reach themes or quotes.
    """
    letters = _LETTER.findall(text)
    if not letters:
        return "other"
    latin = sum(1 for ch in letters if _is_latin(ch))
    if latin / len(letters) < 0.7 or len(letters) - latin > MAX_OTHER_SCRIPT_LETTERS:
        return "other"
    return "hinglish" if hindi_marker_count(text) >= 2 else "en"


def text_key(date: str, text: str) -> str:
    """De-duplication key: calendar day plus case-insensitive text hash."""
    digest = hashlib.sha256(text.lower().encode("utf-8")).hexdigest()
    return "%s:%s" % (date[:10], digest)


def make_review_id(date: str, text: str) -> str:
    """Stable internal id, derived from content only (never from a store id)."""
    return hashlib.sha256(("rid|" + date + "|" + text).encode("utf-8")).hexdigest()[:16]


def dedupe(rows: Iterable[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], int]:
    seen: Set[str] = set()
    out: List[Dict[str, Any]] = []
    dropped = 0
    for row in rows:
        key = text_key(row["date"], row["text"])
        if key in seen:
            dropped += 1
            continue
        seen.add(key)
        out.append(row)
    return out, dropped
