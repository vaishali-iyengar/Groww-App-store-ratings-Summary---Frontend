"""Phase 3: clean reviews -> at most max_themes labelled, ranked themes."""
from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..config import Config
from ..logging_utils import StageLogger
from . import assign, cluster, embed, label, praise, rank

METHODS = ("auto", "cluster", "llm")


class ThemeError(RuntimeError):
    pass


def latest_clean(clean_dir: Path) -> Path:
    files = sorted(clean_dir.glob("reviews_*.jsonl"))
    if not files:
        raise ThemeError("no clean reviews in %s; run `clean` first" % clean_dir)
    return files[-1]


def _cluster_themes(themed, cfg, labeller, encoder) -> List[Dict[str, Any]]:
    vectors = embed.embed_reviews(themed, cfg.path("themes"), cfg.embed_model, encoder)
    labels, centroids = cluster.cluster(vectors, cfg.cluster_k, cfg.max_themes)
    samples = label.build_samples(themed, vectors, labels, centroids, cfg.label_sample)
    names = label.label_clusters(samples, labeller)
    groups = rank.cluster_groups(vectors, labels, centroids)
    return rank.theme_stats(themed, groups, names, "similarity")


def build_themes(
    rows: List[Dict[str, Any]], cfg: Config, labeller: label.Labeller,
    encoder: Optional[embed.Encoder] = None, method: str = "auto",
    proposer: Optional[assign.Proposer] = None, assigner: Optional[assign.Assigner] = None,
    log: Optional[StageLogger] = None,
) -> Dict[str, Any]:
    if method not in METHODS:
        raise ThemeError("method must be one of %s" % ", ".join(METHODS))
    themed, held = praise.split_praise(rows)
    if not themed:
        raise ThemeError("no reviews left after holding out generic praise")

    cluster_gate = None
    other = 0
    used = method
    if method in ("auto", "cluster"):
        themes = _cluster_themes(themed, cfg, labeller, encoder)
        cluster_gate = rank.quality_gate(themes)
        used = "cluster"
        if method == "auto" and not cluster_gate["passed"] and proposer and assigner:
            used = "llm"
    if used == "llm":
        if not (proposer and assigner):
            raise ThemeError("the llm method needs an LLM; drop --no-llm")
        progress = (lambda n, total: log.info("assigning reviews", data={"batch": n, "of": total})) if log else None
        groups, names, other = assign.llm_groups(themed, cfg.max_themes, proposer, assigner, progress)
        themes = rank.theme_stats(themed, groups, names, "confidence")

    weeks = rank.add_week_over_week(themes, themed)
    gate = rank.quality_gate(themes)
    themes = rank.rank(themes, cfg.top_themes)
    return {
        "method": used,
        "review_count": len(rows),
        "themed_count": len(themed),
        "low_confidence": len(rows) < cfg.min_reviews,
        "general_praise": {
            "count": len(held),
            "share": round(len(held) / len(rows), 4),
            "avg_rating": round(sum(r["rating"] for r in held) / len(held), 2) if held else None,
        },
        "other_count": other,
        "embed_model": cfg.embed_model if cluster_gate else None,
        "cluster_gate": cluster_gate if used == "llm" else None,  # why clustering was rejected
        "quality_gate": gate,
        "weeks": weeks,
        "themes": themes,
        "top_themes": [t["theme_id"] for t in themes if t["top"]],
    }


def run(
    cfg: Config, log: StageLogger, clean_path: Optional[Path] = None, use_llm: bool = True,
    labeller: Optional[label.Labeller] = None, encoder: Optional[embed.Encoder] = None,
    fast_embed: bool = False, method: str = "auto",
    proposer: Optional[assign.Proposer] = None, assigner: Optional[assign.Assigner] = None,
) -> Path:
    if fast_embed:
        cfg = replace(cfg, embed_model=embed.LSA_MODEL)
    clean_path = clean_path or latest_clean(cfg.path("clean"))
    with open(clean_path, encoding="utf-8") as fh:
        rows = [json.loads(line) for line in fh if line.strip()]
    if not rows:
        raise ThemeError("no reviews in %s" % clean_path)

    if use_llm:
        try:
            labeller = labeller or label.llm_labeller(cfg.llm_provider, cfg.label_model)
            proposer = proposer or assign.llm_proposer(cfg.llm_provider, cfg.label_model)
            assigner = assigner or assign.llm_assigner(cfg.llm_provider, cfg.label_model)
        except label.LabelError as exc:
            raise ThemeError(str(exc))
    else:
        labeller = labeller or label.keyword_labeller

    try:
        result = build_themes(rows, cfg, labeller, encoder, method, proposer, assigner, log)
    except label.LabelError as exc:
        raise ThemeError(str(exc))
    if len(result["themes"]) > cfg.max_themes:
        raise ThemeError("theme cap exceeded: %d > %d" % (len(result["themes"]), cfg.max_themes))

    run_date = clean_path.stem.split("_", 1)[1]
    result = dict(
        run_date=run_date, source=str(clean_path),
        label_model="%s:%s" % (cfg.llm_provider, cfg.label_model) if use_llm else "keywords", **result,
    )
    out_dir = cfg.path("themes")
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / ("themes_%s.json" % run_date)
    out.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    if result["low_confidence"]:
        log.warning("fewer reviews than min_reviews", data={"reviews": len(rows), "min": cfg.min_reviews})
    if not result["quality_gate"]["passed"]:
        log.warning("theme quality gate failed", data=result["quality_gate"])
    log.info("themes built", data={
        "path": str(out), "method": result["method"], "reviews": len(rows),
        "general_praise": result["general_praise"], "other": result["other_count"],
        "quality_gate": result["quality_gate"],
        "themes": [
            {k: t[k] for k in ("rank", "name", "review_count", "share", "avg_rating", "rank_score", "wow_share_change")}
            for t in result["themes"]
        ],
    })
    return out
