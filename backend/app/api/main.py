"""FastAPI app. Serves the latest evaluated slate, validation report and prediction tracker."""
from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import func, select

from .. import pipeline
from ..backtest.run import load_report
from ..config import get_settings
from ..db import FetchLog, Game, PlayerGameLog, session
from ..explain import explain
from ..providers import odds_api

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
app = FastAPI(title="NBA Prop Research API", version="1.0")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
                   allow_methods=["GET", "POST"], allow_headers=["*"])


def _dump(x):
    return JSONResponse(json.loads(json.dumps(x, default=str)))


@app.get("/api/health")
def health():
    with session() as s:
        n_logs = s.scalar(select(func.count()).select_from(PlayerGameLog))
        n_games = s.scalar(select(func.count()).select_from(Game).where(Game.box_loaded.is_(True)))
    return {"ok": True, "player_game_logs": n_logs, "games_with_box_scores": n_games, "pipeline": pipeline.state,
            "espn_enabled": get_settings().espn_enabled, "odds_api_enabled": odds_api.enabled()}


@app.get("/api/slate")
def slate():
    if not pipeline.SLATE_PATH.exists():
        return _dump({"overview": None, "candidates": [], "slate": [], "pipeline": pipeline.state,
                      "message": "No evaluation yet. Press Refresh."})
    data = json.loads(pipeline.SLATE_PATH.read_text())
    today = pipeline.today_slate()
    data["is_today"] = data.get("overview", {}).get("slate_date") == today
    data["today"] = today
    data["pipeline"] = pipeline.state
    for c in data.get("candidates", []) + data.get("high_probability", []):
        c["explanation"] = c.get("explanation") or explain(c)
    return _dump(data)


@app.post("/api/refresh")
def refresh():
    started = pipeline.run_async()
    return {"started": started, "message": "Refresh started." if started else "A refresh is already running."}


@app.get("/api/status")
def status():
    return _dump(pipeline.state)


@app.get("/api/validation")
def validation():
    rep = load_report()
    if not rep:
        raise HTTPException(404, "No validation report. Run `make backtest`.")
    return _dump(rep)


@app.get("/api/tracker")
def tracker():
    return _dump(pipeline.tracker_summary())


@app.get("/api/sources")
def sources():
    with session() as s:
        rows = s.execute(select(FetchLog.source, func.count(), func.sum(FetchLog.ok.cast(int)), func.max(FetchLog.at))
                         .group_by(FetchLog.source)).all()
    return _dump([{"source": r[0], "requests": r[1], "ok": r[2], "last": r[3]} for r in rows])


@app.get("/api/config")
def config():
    s = get_settings()
    return {"timezone": s.timezone, "auto_refresh_min": s.auto_refresh_min, "odds_stale_after_min": s.odds_stale_after_min,
            "min_games_current_season": s.min_games_current_season, "max_minutes_cv": s.max_minutes_cv,
            "max_prob_sd": s.max_prob_sd, "max_model_disagreement": s.max_model_disagreement,
            "odds_api_enabled": odds_api.enabled(), "llm_enabled": bool(s.anthropic_api_key), "paper_mode": True}


def _auto_refresh():
    """Refresh on an interval during slate hours. Each refresh costs ~1 ESPN call per game (+ Odds API credits if keyed)."""
    s = get_settings()
    time.sleep(5)
    while True:
        try:
            local_hour = datetime.now(ZoneInfo(s.timezone)).hour
            if 9 <= local_hour <= 23 or not pipeline.SLATE_PATH.exists():
                pipeline.run_async()
        except Exception:
            logging.exception("auto refresh failed")
        time.sleep(max(5, s.auto_refresh_min) * 60)


@app.on_event("startup")
def _start():
    if get_settings().auto_refresh_min > 0:
        threading.Thread(target=_auto_refresh, daemon=True).start()
