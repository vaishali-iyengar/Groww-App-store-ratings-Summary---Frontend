"""Per-theme stats, in-window week-over-week change, quality gate and ranking."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

# One theme's members as (row index, score), best quote candidate first.
Group = List[Tuple[int, float]]

MAX_LARGEST_SHARE = 0.35
MIN_THEME_SHARE = 0.03
MIN_WEEK_COUNT = 10


def cluster_groups(vectors: np.ndarray, labels: np.ndarray, centroids: np.ndarray) -> List[Group]:
    """Members of each cluster, closest to the centre first."""
    groups = []
    for c, cent in enumerate(centroids):
        idx = np.flatnonzero(labels == c)
        sims = vectors[idx] @ cent
        order = np.argsort(-sims, kind="stable")
        groups.append([(int(idx[j]), float(sims[j])) for j in order])
    return groups


def theme_stats(
    rows: List[Dict[str, Any]], groups: Sequence[Group], names: List[Dict[str, str]], score_key: str,
) -> List[Dict[str, Any]]:
    total = len(rows)
    themes = []
    for c, group in enumerate(groups):
        avg = float(np.mean([rows[i]["rating"] for i, _ in group]))
        share = len(group) / total
        themes.append({
            "theme_id": "t%d" % (c + 1),
            "name": names[c]["name"],
            "description": names[c]["description"],
            "review_count": len(group),
            "share": round(share, 4),
            "avg_rating": round(avg, 2),
            "rank_score": round(share * (5 - avg), 4),
            # Best quote candidates first; Phase 4 picks quotes from the top of this list.
            "members": [{"review_id": rows[i]["review_id"], score_key: round(s, 4)} for i, s in group],
        })
    return themes


def complete_weeks(rows: List[Dict[str, Any]]) -> List[date]:
    """Mondays of ISO weeks that lie fully inside the data's date range, oldest first."""
    days = sorted(date.fromisoformat(r["date"][:10]) for r in rows)
    first, last = days[0], days[-1]
    monday = first - timedelta(days=first.weekday())
    if monday < first:
        monday += timedelta(weeks=1)
    weeks = []
    while monday + timedelta(days=6) <= last:
        weeks.append(monday)
        monday += timedelta(weeks=1)
    return weeks


def add_week_over_week(themes: List[Dict[str, Any]], rows: List[Dict[str, Any]]) -> Optional[Dict[str, str]]:
    """Each theme's share in the last complete week minus its share in the week before.

    Shares are of all themed reviews that week. None when either week has fewer than
    MIN_WEEK_COUNT reviews in the theme, or when there are not two complete weeks.
    """
    for t in themes:
        t["wow_share_change"] = None
        t["week_counts"] = None
    weeks = complete_weeks(rows)
    if len(weeks) < 2:
        return None
    prev, last = weeks[-2], weeks[-1]

    def week_of(r: Dict[str, Any]) -> date:
        d = date.fromisoformat(r["date"][:10])
        return d - timedelta(days=d.weekday())

    week_by_id = {r["review_id"]: week_of(r) for r in rows}
    totals = {w: sum(1 for v in week_by_id.values() if v == w) for w in (prev, last)}
    for t in themes:
        counts = {w: sum(1 for m in t["members"] if week_by_id[m["review_id"]] == w) for w in (prev, last)}
        t["week_counts"] = {"previous": counts[prev], "last": counts[last]}
        if min(counts.values()) >= MIN_WEEK_COUNT:
            t["wow_share_change"] = round(counts[last] / totals[last] - counts[prev] / totals[prev], 4)
    return {"previous_week": prev.isoformat(), "last_week": last.isoformat()}


def quality_gate(themes: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Largest theme <= 35% of themed reviews and every theme >= 3%."""
    shares = [t["share"] for t in themes]
    largest, smallest = max(shares), min(shares)
    return {
        "largest_share": largest,
        "smallest_share": smallest,
        "max_largest_share": MAX_LARGEST_SHARE,
        "min_theme_share": MIN_THEME_SHARE,
        "passed": largest <= MAX_LARGEST_SHARE and smallest >= MIN_THEME_SHARE,
    }


def rank(themes: List[Dict[str, Any]], top_n: int) -> List[Dict[str, Any]]:
    """Order by score = share x (5 - avg rating), theme_id breaking ties; mark the top N."""
    ranked = sorted(themes, key=lambda t: (-t["rank_score"], t["theme_id"]))
    for i, t in enumerate(ranked, 1):
        t["rank"] = i
        t["top"] = i <= top_n
    return ranked
