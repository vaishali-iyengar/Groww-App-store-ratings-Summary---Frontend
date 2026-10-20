"""Phase 4: ranked themes -> validated pulse note in data/runs/<run_id>/."""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..config import Config
from ..logging_utils import StageLogger
from ..validate import validate, word_count
from . import quotes as quote_picker
from . import render, writer as writers

ATTEMPTS = 2  # first draft plus one regeneration


class PulseError(RuntimeError):
    pass


def latest_themes(themes_dir: Path) -> Path:
    files = sorted(themes_dir.glob("themes_*.json"))
    if not files:
        raise PulseError("no themes in %s; run `themes` first" % themes_dir)
    return files[-1]


def previous_top(themes_dir: Path, run_date: str) -> Optional[List[str]]:
    older = [p for p in sorted(themes_dir.glob("themes_*.json")) if p.stem.split("_", 1)[1] < run_date]
    if not older:
        return None
    prev = json.loads(older[-1].read_text())
    return [t["name"] for t in prev["themes"] if t.get("top")]


def build_pulse(
    themes: Dict[str, Any], rows: Dict[str, Dict[str, Any]], cfg: Config, writer: writers.Writer,
    previous: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Pick quotes, draft, render and validate; regenerate once with the failures as feedback."""
    top = [t for t in themes["themes"] if t.get("top")]
    if len(top) < cfg.top_themes:
        raise PulseError("themes file has %d top themes, need %d" % (len(top), cfg.top_themes))
    pools = quote_picker.candidate_pools(top, rows)

    days = sorted(r["date"][:10] for r in rows.values())
    # Label the note by the last full week: the week holding the day before the fetch. A Monday
    # morning run would otherwise be "week of <today>" with only hours of reviews.
    if themes.get("run_date"):
        last = datetime.strptime(themes["run_date"], "%Y%m%d").date() - timedelta(days=1)
    else:
        last = date.fromisoformat(days[-1])
    themes = dict(themes, week_of=(last - timedelta(days=last.weekday())).isoformat())
    window = {"start": days[0], "end": days[-1]}
    context = writers.build_context(themes, top, pools, previous)

    feedback: Optional[List[str]] = None
    attempts = []
    for _ in range(ATTEMPTS):
        fields = writer(context, feedback)
        note = render.build_note(context, fields, pools, window)
        markdown = render.render(note)
        failures = validate(note, markdown, rows, themes, cfg.max_words, cfg.max_themes, cfg.top_themes)
        attempts.append(failures)
        if not failures:
            break
        feedback = failures
    return {"note": note, "markdown": markdown, "failures": failures, "attempts": attempts,
            "words": word_count(markdown)}


def run(
    cfg: Config, log: StageLogger, run_id: str, themes_path: Optional[Path] = None, use_llm: bool = True,
    writer: Optional[writers.Writer] = None,
) -> Path:
    themes_dir = cfg.path("themes")
    themes_path = themes_path or latest_themes(themes_dir)
    themes = json.loads(themes_path.read_text())
    with open(themes["source"], encoding="utf-8") as fh:
        rows = {r["review_id"]: r for r in (json.loads(line) for line in fh if line.strip())}

    try:
        if writer is None:
            writer = writers.llm_writer(cfg.llm_provider, cfg.writer_model) if use_llm else writers.template_writer
        result = build_pulse(themes, rows, cfg, writer, previous_top(themes_dir, themes["run_date"]))
    except writers.WriterError as exc:
        raise PulseError(str(exc))

    out_dir = cfg.path("runs") / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    record = {
        "run_id": run_id, "themes": str(themes_path), "writer": "%s:%s" % (cfg.llm_provider, cfg.writer_model) if use_llm else "template",
        "words": result["words"], "validation": {"passed": not result["failures"], "attempts": result["attempts"]},
        "note": result["note"],
    }
    (out_dir / "pulse.json").write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if result["failures"]:
        # Keep the failed draft locally for inspection; nothing is published.
        (out_dir / "pulse_failed.md").write_text(result["markdown"], encoding="utf-8")
        log.error("validation failed twice", data={"failures": result["failures"], "dir": str(out_dir)})
        raise PulseError("validation failed after regeneration: %s" % "; ".join(result["failures"]))

    out = out_dir / "pulse.md"
    out.write_text(result["markdown"], encoding="utf-8")
    log.info("pulse written", data={
        "path": str(out), "words": result["words"], "attempts": len(result["attempts"]),
        "quotes": [{k: q[k] for k in ("theme_id", "review_id", "start", "end")} for q in result["note"]["quotes"]],
    })
    return out
