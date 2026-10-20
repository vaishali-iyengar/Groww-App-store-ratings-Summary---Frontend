"""Simulator: run themes and pulse in memory on the last N weeks of the latest clean snapshot.

Nothing is written to data/themes/ or data/runs/ (apart from the shared embedding cache), so the
weekly job never picks up a simulator result, and nothing is delivered over MCP.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from ..config import Config
from ..logging_utils import get_logger, new_run_id

MIN_WEEKS, MAX_WEEKS = 1, 10
MIN_SIM_REVIEWS = 20  # below this, clustering into 3+ themes is not meaningful

# progress(stage) with stage in STAGES
Progress = Callable[[str], None]
STAGES = ("filtering", "theming", "writing")


class SimError(RuntimeError):
    pass


def load_snapshot(cfg: Config) -> Tuple[str, datetime, List[Dict[str, Any]]]:
    """(snapshot id, snapshot date, rows) for the newest clean review file."""
    files = sorted(cfg.path("clean").glob("reviews_*.jsonl"))
    if not files:
        raise SimError("No cleaned reviews found. Run `python -m src.main run` once to fetch them.")
    path = files[-1]
    snap_id = path.stem.split("_", 1)[1]
    with open(path, encoding="utf-8") as fh:
        rows = [json.loads(line) for line in fh if line.strip()]
    return snap_id, datetime.strptime(snap_id, "%Y%m%d"), rows


def weekly_counts(rows: List[Dict[str, Any]], snap: datetime, weeks: int = MAX_WEEKS) -> List[Dict[str, Any]]:
    """Review count per week before the snapshot, oldest first. weeks_back=1 is the most recent week."""
    out = []
    for back in range(weeks, 0, -1):
        start, end = snap - timedelta(weeks=back), snap - timedelta(weeks=back - 1)
        n = sum(1 for r in rows if start <= datetime.fromisoformat(r["date"]) < end)
        out.append({"weeks_back": back, "start": start.date().isoformat(),
                    "end": (end - timedelta(days=1)).date().isoformat(), "count": n})
    return out


def filter_weeks(rows: List[Dict[str, Any]], snap: datetime, weeks: int) -> List[Dict[str, Any]]:
    cutoff = snap - timedelta(weeks=weeks)
    return [r for r in rows if cutoff <= datetime.fromisoformat(r["date"]) < snap]


def _key_name(cfg: Config) -> str:
    from ..llm import PROVIDERS

    return PROVIDERS.get(cfg.llm_provider, "LLM API key")


def simulate(
    cfg: Config, weeks: int, use_llm: bool = True, progress: Optional[Progress] = None,
    labeller: Any = None, proposer: Any = None, assigner: Any = None, writer: Any = None, encoder: Any = None,
) -> Dict[str, Any]:
    from ..pulse import pipeline as pulse
    from ..pulse import writer as writers
    from ..themes import assign, embed, label
    from ..themes import pipeline as themes_pipeline

    if not MIN_WEEKS <= weeks <= MAX_WEEKS:
        raise SimError("Weeks must be between %d and %d." % (MIN_WEEKS, MAX_WEEKS))
    progress = progress or (lambda stage: None)
    run_id = new_run_id()
    log = get_logger(run_id, "simulate")

    progress("filtering")
    snap_id, snap, all_rows = load_snapshot(cfg)
    rows = filter_weeks(all_rows, snap, weeks)
    if len(rows) < MIN_SIM_REVIEWS:
        raise SimError("Only %d reviews in the last %d week(s). Pick more weeks to get at least %d."
                       % (len(rows), weeks, MIN_SIM_REVIEWS))
    log.info("simulating", data={"snapshot": snap_id, "weeks": weeks, "reviews": len(rows), "llm": use_llm})

    progress("theming")
    try:
        if use_llm:
            labeller = labeller or label.llm_labeller(cfg.llm_provider, cfg.label_model)
            proposer = proposer or assign.llm_proposer(cfg.llm_provider, cfg.label_model)
            assigner = assigner or assign.llm_assigner(cfg.llm_provider, cfg.label_model)
        else:
            labeller = labeller or label.keyword_labeller
        themes = themes_pipeline.build_themes(rows, cfg, labeller, encoder, "auto", proposer, assigner, log)
    except (label.LabelError, themes_pipeline.ThemeError) as exc:
        if "is not set" in str(exc):  # missing API key: say how to fix it from the page's point of view
            raise SimError("The server has no %s. Export it in the terminal that starts the simulator and "
                           "restart it, or tick Offline mode." % _key_name(cfg))
        raise SimError("Theme step failed: %s" % exc)
    except embed.EmbeddingError as exc:
        raise SimError(str(exc))
    themes = dict(themes, run_date=snap_id, source="simulator")

    progress("writing")
    try:
        writer = writer or (writers.llm_writer(cfg.llm_provider, cfg.writer_model) if use_llm
                            else writers.template_writer)
        result = pulse.build_pulse(themes, {r["review_id"]: r for r in rows}, cfg, writer)
    except (writers.WriterError, pulse.PulseError) as exc:
        raise SimError("Pulse step failed: %s" % exc)
    if result["failures"]:
        raise SimError("The pulse failed validation twice: %s" % "; ".join(result["failures"]))

    note = result["note"]
    return {
        "run_id": run_id, "snapshot": snap_id, "weeks": weeks, "mode": "llm" if use_llm else "offline",
        "window": note["window"], "week_of": note["week_of"], "review_count": note["review_count"],
        "low_confidence": note["low_confidence"], "min_reviews": cfg.min_reviews,
        "headline": note["headline"], "themes": note["themes"], "quotes": note["quotes"],
        "actions": note["actions"], "words": result["words"], "markdown": result["markdown"],
    }
