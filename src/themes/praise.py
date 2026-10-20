"""Hold out generic praise ("very good app") so it does not pull clusters into a catch-all."""
from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple

MAX_WORDS = 12
MIN_RATING = 4

# Any of these means the review says something specific, so it is clustered even if short.
_TOPIC = re.compile(
    r"kyc|verif|onboard|aadhaar|\bpan\b|sign ?up|regist|withdraw|payout|refund|credit|settle|"
    r"\bupi\b|add money|deposit|payment|mandate|autopay|charge|brokerage|fee|hidden|commission|"
    r"crash|slow|lag|hang|bug|glitch|not work|error|load|stuck|freez|support|customer care|"
    r"helpline|ticket|call|chat|chart|candle|indicator|f&o|option|future|intraday|order|"
    r"mutual fund|\bsip\b|\bmf\b|\bnav\b|\bipo\b|stock|share|statement|tax|p&l|pnl|report|"
    r"update|\bui\b|interface|design|version|layout|feature|add|please|plz|should|fraud|scam|"
    r"cheat|loss|lost|money|but|however|except|problem|issue",
    re.IGNORECASE,
)


def is_generic_praise(row: Dict[str, Any]) -> bool:
    text = row["text"]
    return row["rating"] >= MIN_RATING and len(text.split()) <= MAX_WORDS and not _TOPIC.search(text)


def split_praise(rows: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Return (rows to theme, generic praise rows)."""
    themed, praise = [], []
    for row in rows:
        (praise if is_generic_praise(row) else themed).append(row)
    return themed, praise
