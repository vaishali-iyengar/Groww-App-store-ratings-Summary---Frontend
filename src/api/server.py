"""FastAPI app for the pulse simulator: a week picker page plus a small job API.

POST /api/pulse starts a background job (themes + pulse take tens of seconds with the LLM);
the page polls GET /api/pulse/{job_id}. Results are cached per (snapshot, weeks, mode).

With PULSE_SYNC=1 (Vercel, where background threads and in-memory jobs don't survive between
requests) POST /api/pulse runs the pulse inline and returns the result in the same response.
"""
from __future__ import annotations

import os
import threading
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from ..config import ROOT, Config, load_config
from . import simulate as sim

WEB = ROOT / "web"

# runner(cfg, weeks, use_llm, progress) -> result dict
Runner = Callable[..., Dict[str, Any]]


class PulseRequest(BaseModel):
    weeks: int = Field(ge=sim.MIN_WEEKS, le=sim.MAX_WEEKS)
    use_llm: bool = True


def create_app(cfg: Optional[Config] = None, runner: Optional[Runner] = None,
               sync: Optional[bool] = None) -> FastAPI:
    cfg = cfg or load_config()
    runner = runner or sim.simulate
    sync = bool(os.environ.get("PULSE_SYNC")) if sync is None else sync
    app = FastAPI(title="Pulse Simulator")
    jobs: Dict[str, Dict[str, Any]] = {}
    cache: Dict[tuple, Dict[str, Any]] = {}
    lock = threading.Lock()

    def work(job_id: str, key: tuple, req: PulseRequest) -> None:
        job = jobs[job_id]

        def progress(stage: str) -> None:
            job["status"] = stage

        try:
            result = runner(cfg, req.weeks, req.use_llm, progress)
            cache[key] = result
            job.update(status="done", result=result)
        except sim.SimError as exc:
            job.update(status="failed", error=str(exc))
        except Exception as exc:  # surface anything unexpected instead of hanging the page
            job.update(status="failed", error="%s: %s" % (type(exc).__name__, exc))

    @app.get("/api/snapshot")
    def snapshot() -> Dict[str, Any]:
        try:
            snap_id, snap, rows = sim.load_snapshot(cfg)
        except sim.SimError as exc:
            raise HTTPException(404, str(exc))
        return {"snapshot": snap_id, "min_weeks": sim.MIN_WEEKS, "max_weeks": sim.MAX_WEEKS,
                "min_reviews": cfg.min_reviews, "sync": sync, "weeks": sim.weekly_counts(rows, snap)}

    @app.post("/api/pulse")
    def start(req: PulseRequest) -> Dict[str, Any]:
        try:
            snap_id = sim.load_snapshot(cfg)[0]
        except sim.SimError as exc:
            raise HTTPException(404, str(exc))
        key = (snap_id, req.weeks, req.use_llm)
        if sync:
            if key not in cache:
                try:
                    cache[key] = runner(cfg, req.weeks, req.use_llm, lambda stage: None)
                except sim.SimError as exc:
                    raise HTTPException(400, str(exc))
            return {"status": "done", "result": cache[key]}
        job_id = uuid.uuid4().hex[:12]
        with lock:
            if key in cache:
                jobs[job_id] = {"status": "done", "result": cache[key], "cached": True}
                return {"job_id": job_id}
            if any(j["status"] not in ("done", "failed") for j in jobs.values()):
                raise HTTPException(409, "A pulse is already running. Wait for it to finish.")
            jobs[job_id] = {"status": "queued"}
        threading.Thread(target=work, args=(job_id, key, req), daemon=True).start()
        return {"job_id": job_id}

    @app.get("/api/pulse/{job_id}")
    def status(job_id: str) -> Dict[str, Any]:
        if job_id not in jobs:
            raise HTTPException(404, "Unknown job")
        return jobs[job_id]

    if WEB.is_dir():  # local runs; on Vercel the CDN serves public/ instead
        @app.get("/", include_in_schema=False)
        def index() -> FileResponse:
            return FileResponse(WEB / "index.html")

        app.mount("/static", StaticFiles(directory=WEB), name="static")
    return app
