"""PII masking and detection for review text.

Patterns run in a fixed order so that a more specific type (for example an
email) is masked before a looser one (for example a UPI id). Free-text names
cannot be detected reliably by pattern; reviewer names are never read in the
first place (see ingest), so this covers identifiers a reviewer typed in.
"""
from __future__ import annotations

import re
from typing import Dict, List, Pattern, Tuple

_SURNAMES = (
    "Agarwal|Aggarwal|Agrawal|Ahuja|Ansari|Bansal|Banerjee|Bhatia|Chatterjee|Chauhan|Chopra|Das|Desai|"
    "Dubey|Gandhi|Garg|Ghosh|Goel|Gupta|Iyer|Jain|Joshi|Kapoor|Khan|Khanna|Kulkarni|Kumar|Malhotra|"
    "Mehra|Mehta|Mishra|Mukherjee|Nair|Pandey|Patel|Pillai|Rao|Reddy|Saxena|Shah|Sharma|Shetty|"
    "Singh|Sinha|Srivastava|Tiwari|Trivedi|Verma|Yadav"
)

# (name, placeholder, regex), applied in order.
_PATTERNS: List[Tuple[str, str, Pattern[str]]] = [
    ("email", "[email]", re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")),
    ("link", "[link]", re.compile(r"(?:https?://|www\.)\S+", re.I)),
    # UPI id such as name@okhdfcbank (no dot in the handle, so not matched as email)
    ("id", "[id]", re.compile(r"(?<![\w@])[\w.\-]{2,}@[a-zA-Z]{2,}\b")),
    # PAN: 5 letters, 4 digits, 1 letter
    ("id", "[id]", re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b")),
    # Indian mobile: optional +91 / 91 / 0, then 10 digits starting 6-9 (optionally 5+5)
    ("phone", "[phone]", re.compile(r"(?<![\d])(?:\+?91[\s-]?|0)?[6-9]\d{4}[\s-]?\d{5}(?!\d)")),
    # Aadhaar: 12 digits, optionally grouped 4-4-4
    ("id", "[id]", re.compile(r"(?<!\d)\d{4}[\s-]?\d{4}[\s-]?\d{4}(?!\d)")),
    # Names: "my name is X", "Mr X", or one/two capitalised words before a common Indian surname
    ("name", "[name]", re.compile(
        r"(?i:\bmy name is\s+|\bmyself\s+|\b(?:mr|mrs|ms|miss|shri|smt)\.?\s+)[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?"
    )),
    ("name", "[name]", re.compile(r"\b(?:[A-Z][a-z]{2,}\s+){1,2}(?:%s)\b" % _SURNAMES)),
    # Account / card-like numbers: 9 to 18 consecutive digits
    ("id", "[id]", re.compile(r"(?<!\d)\d{9,18}(?!\d)")),
]


def mask(text: str) -> Tuple[str, Dict[str, int]]:
    """Return the masked text and a count of masks per type."""
    counts: Dict[str, int] = {}
    for name, placeholder, pattern in _PATTERNS:
        text, n = pattern.subn(placeholder, text)
        if n:
            counts[name] = counts.get(name, 0) + n
    return text, counts


def find_pii(text: str) -> List[str]:
    """Types of PII still present in text (empty list means clean)."""
    return sorted({name for name, _, pattern in _PATTERNS if pattern.search(text)})
