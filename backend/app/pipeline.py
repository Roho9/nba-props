"""Daily workflow: refresh -> features -> distributions -> market math -> filters -> stress -> rank ->
publish (immutable) -> invalidate on material change -> settle finished games."""
from __future__ import annotations

import hashlib
import json
import logging
import threading
import traceback
from collections import defaultdict
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
from sqlalchemy import func, select

from . import ingest
from .backtest.run import load_report
from .config import BACKEND_DIR, get_settings
from .db import FetchLog, Game, InjuryReport, ModelRun, OddsSnapshot, Prediction, Team, get_engine, session, utcnow
from .models.engine import (MARKET_LABEL, MODEL_VERSION, STAT_COMPONENTS, GameContext, History, project,
                            project_double_double, to_day)
from .odds import ev_per_unit, fair_american, implied_prob, no_vig_two_way, settle
from .risk.engine import Gate, evaluate_quote, pick_top, player_flags, risk_class, stress_flags, stress_test

log = logging.getLogger("pipeline")
SLATE_PATH = BACKEND_DIR / "data" / "latest_slate.json"
_lock = threading.Lock()
state = {"running": False, "last_error": None, "last_started": None}


def today_slate() -> str:
    return datetime.now(ZoneInfo(get_settings().timezone)).date().isoformat()


def current_gate() -> tuple[Gate, dict | None]:
    rep = load_report()
    if not rep:
        return Gate(False, 1.0, 0.0, "No validation report yet: run `make backtest`."), None
    bv = rep.get("betting_validation", {})
    ok = rep.get("status") == "passed"
    w = float(bv.get("current_blend_weight", 1.0)) if bv.get("current_blend_weight") is not None else 1.0
    reason = "Walk-forward validation passed." if ok else " ".join(bv.get("reasons") or ["Validation did not pass."])
    calib = tuple(bv.get("current_calibration") or (0.0, 1.0))
    return Gate(ok, w, float(bv.get("current_min_edge", 0.0) or 0.0), reason, calib), rep


def latest_injuries() -> tuple[dict[str, dict], datetime | None]:
    with session() as s:
        at = s.scalar(select(func.max(InjuryReport.retrieved_at)))
        if at is None:
            return {}, None
        rows = s.scalars(select(InjuryReport).where(InjuryReport.retrieved_at == at)).all()
    return {r.athlete_id: {"status": r.status, "comment": r.comment, "reported_at": r.reported_at, "name": r.athlete_name,
                           "team_id": r.team_id, "url": r.source_url} for r in rows}, at


def latest_quotes(game_ids: list[str]) -> pd.DataFrame:
    with get_engine().connect() as c:
        df = pd.read_sql(select(OddsSnapshot).where(OddsSnapshot.game_id.in_(game_ids), OddsSnapshot.is_historical_close.is_(False)), c)
    if df.empty:
        return df
    df = df.sort_values("retrieved_at")
    latest_pull = df.groupby(["game_id", "source"])["retrieved_at"].transform("max")
    cur = df[df["retrieved_at"] == latest_pull]  # only quotes present in the latest pull of each board
    first = df.drop_duplicates(["game_id", "athlete_id", "market", "kind", "line", "side", "book"], keep="first")
    first = first.set_index(["game_id", "athlete_id", "market", "kind", "line", "side", "book"])
    cur = cur.drop_duplicates(["game_id", "athlete_id", "market", "kind", "line", "side", "book"], keep="last").copy()
    key = list(zip(cur["game_id"], cur["athlete_id"], cur["market"], cur["kind"], cur["line"], cur["side"], cur["book"]))
    cur["first_seen_american"] = [first["american"].get(k) for k in key]
    cur["first_seen_at"] = [first["retrieved_at"].get(k) for k in key]
    return cur


def _ctx(h: History, g, team_id: str, injuries: dict) -> GameContext:
    home = team_id == g.home_team_id
    opp = g.away_team_id if home else g.home_team_id
    spread = None if g.spread_home is None else (g.spread_home if home else -g.spread_home)
    day = int(to_day([g.game_date])[0])
    tl = h.team_games_before(team_id, day).tail(1)
    b2b = bool(len(tl) and int(tl["day"].iloc[0]) == day - 1)
    known_out = [a for a, i in injuries.items() if i["team_id"] == team_id and i["status"].lower() == "out"]
    return GameContext(g.game_id, team_id, opp, home, spread, g.total, known_out, b2b)


def _history_payload(h: History, aid: str, market: str, day: int, line: float, opp: str, teams) -> dict:
    hist = h.player_before(aid, day)
    played = hist[(~hist["dnp"]) & (hist["minutes"] > 0)]
    comps = STAT_COMPONENTS.get(market, ["pts", "reb", "ast"])
    vals = played[comps].sum(axis=1) if market != "dd" else played[["pts", "reb", "ast"]].max(axis=1)
    out = {}
    for n in (5, 10, 15, 20, 30):
        v = vals.tail(n).to_numpy(float)
        if len(v) == 0:
            continue
        out[f"L{n}"] = {"n": int(len(v)), "mean": round(float(v.mean()), 2), "median": float(np.median(v)),
                        "sd": round(float(v.std(ddof=1)) if len(v) > 1 else 0.0, 2),
                        "iqr": [float(np.percentile(v, 25)), float(np.percentile(v, 75))], "min": float(v.min()),
                        "max": float(v.max()), "hit_rate_vs_line": round(float((v > line).mean()), 3),
                        "hits": int((v > line).sum())}
    def season_block(season):
        v = vals[played["season"] == season].to_numpy(float)
        if not len(v):
            return None
        from scipy.stats import skew
        n = len(v)
        se = v.std(ddof=1) / np.sqrt(n) if n > 1 else 0.0
        return {"n": n, "mean": round(float(v.mean()), 2), "median": float(np.median(v)), "sd": round(float(v.std(ddof=1)) if n > 1 else 0, 2),
                "ci95_mean": [round(float(v.mean() - 1.96 * se), 2), round(float(v.mean() + 1.96 * se), 2)],
                "skew": round(float(skew(v)) if n > 2 else 0.0, 3), "hit_rate_vs_line": round(float((v > line).mean()), 3)}
    seasons = sorted(played["season"].unique())
    cur_season = seasons[-1] if seasons else None
    games = []
    for _, r in played.tail(30).iterrows():
        v = float(sum(r[c] for c in comps)) if market != "dd" else None
        games.append({"date": r["game_date"], "opp": teams.get(r["opp_team_id"], r["opp_team_id"]), "home": bool(r["home"]),
                      "minutes": float(r["minutes"]), "value": v, "pts": int(r["pts"]), "reb": int(r["reb"]), "ast": int(r["ast"]),
                      "fg3m": int(r["fg3m"]), "stl": int(r["stl"]), "blk": int(r["blk"]), "tov": int(r["tov"]),
                      "starter": bool(r["starter"]), "usage_proxy": round(float((r["fga"] + 0.44 * r["fta"] + r["tov"]) / max(r["minutes"], 1) * 36), 2),
                      "hit": None if v is None else bool(v > line), "game_id": r["game_id"]})
    cur_rows = played[played["season"] == cur_season] if cur_season else played.iloc[0:0]
    split = {}
    for k, sub in (("home", cur_rows[cur_rows["home"]]), ("away", cur_rows[~cur_rows["home"]])):
        vv = sub[comps].sum(axis=1)
        split[k] = {"n": int(len(vv)), "mean": round(float(vv.mean()), 2) if len(vv) else None,
                    "hit_rate_vs_line": round(float((vv > line).mean()), 3) if len(vv) else None}
    vs = played[played["opp_team_id"] == opp]
    vv = vs[comps].sum(axis=1)
    return {"windows": out, "current_season": season_block(cur_season) if cur_season else None,
            "previous_season": season_block(seasons[-2]) if len(seasons) > 1 else None, "games": games, "home_away": split,
            "vs_opponent": {"n": int(len(vv)), "mean": round(float(vv.mean()), 2) if len(vv) else None,
                            "values": vv.tolist()[-6:],
                            "note": "Small samples across seasons and roster changes: shown for context, not used by the model."}}


def _injury_signature(injuries: dict, team_ids: set[str]) -> str:
    items = sorted((a, i["status"]) for a, i in injuries.items() if i["team_id"] in team_ids)
    return hashlib.sha1(json.dumps(items).encode()).hexdigest()[:16]


def evaluate(slate: str, refresh: bool = True) -> dict:
    s = get_settings()
    started = utcnow()
    with session() as ss:
        run = ModelRun(slate_date=slate, model_version=MODEL_VERSION, status="running")
        ss.add(run)
        ss.commit()
        run_id = run.run_id
    try:
        refresh_report = ingest.refresh_slate(slate) if refresh else {"skipped": True}
        result = _evaluate(slate, run_id, refresh_report)
        invalidate(slate, result)
        settle_predictions()
        result["tracker"] = tracker_summary()
        SLATE_PATH.write_text(json.dumps(_clean(result), default=str, allow_nan=False))
        with session() as ss:
            r = ss.get(ModelRun, run_id)
            r.status, r.finished_at = "ok", utcnow()
            r.summary = json.loads(json.dumps(_clean(result["overview"]), default=str))
            ss.commit()
        return result
    except Exception as e:
        with session() as ss:
            r = ss.get(ModelRun, run_id)
            r.status, r.finished_at, r.error = "failed", utcnow(), traceback.format_exc()[-4000:]
            ss.commit()
        raise


def _evaluate(slate: str, run_id: int, refresh_report: dict) -> dict:
    s = get_settings()
    now = utcnow()
    gate, report = current_gate()
    h = History()
    teams = h.teams["abbr"].to_dict()
    with session() as ss:
        games = ss.scalars(select(Game).where(Game.game_date == slate).order_by(Game.start_time)).all()
    injuries, inj_at = latest_injuries()
    pre_games = [g for g in games if g.start_time > now and g.status == "STATUS_SCHEDULED"]
    started_games = [g for g in games if g not in pre_games]
    quotes = latest_quotes([g.game_id for g in pre_games]) if pre_games else pd.DataFrame()
    gmap = {g.game_id: g for g in games}
    day = int(to_day([slate])[0])
    rows, candidates, coverage = [], [], defaultdict(lambda: {"main_props": 0, "alt_props": 0, "players": set()})
    proj_cache = {}
    if not quotes.empty:
        quotes = quotes.copy()
        stale_cut = now - timedelta(minutes=s.odds_stale_after_min)
        for (gid, aid, mkt), grp in quotes.groupby(["game_id", "athlete_id", "market"]):
            g = gmap[gid]
            name = grp["athlete_name"].dropna().iloc[0] if grp["athlete_name"].notna().any() else h.players["name"].get(aid, aid)
            team_id = h.players["team_id"].get(aid)
            last = h.player_before(aid, day).tail(1)
            if len(last):
                team_id = last["team_id"].iloc[0]
            if team_id not in (g.home_team_id, g.away_team_id):
                team_id = None
            cov = coverage[gid]
            cov["players"].add(aid)
            base = {"game_id": gid, "athlete_id": aid, "athlete_name": name, "market": mkt,
                    "market_label": MARKET_LABEL.get(mkt, mkt), "game_start": g.start_time,
                    "team": teams.get(team_id, "?") if team_id else "?",
                    "opp": teams.get(g.away_team_id if team_id == g.home_team_id else g.home_team_id, "?") if team_id else "?",
                    "matchup": f"{teams.get(g.away_team_id)} @ {teams.get(g.home_team_id)}"}
            inj = injuries.get(aid)
            if team_id is None:
                for _, q in grp.iterrows():
                    rows.append({**base, "line": q["line"], "side": q["side"], "kind": q["kind"], "book": q["book"],
                                 "american": int(q["american"]), "status": "rejected", "risk": "Excluded",
                                 "reasons": [{"code": "no_history", "severity": "exclude", "text": "No game log on file for this player."}]})
                continue
            ctx = _ctx(h, g, team_id, injuries)
            if mkt == "dd":
                dd = project_double_double(h, aid, day, g.season, ctx)
                for _, q in grp.iterrows():
                    p = dd["p_yes"] if dd else None
                    rows.append({**base, "line": 0.5, "side": "yes", "kind": "yes_no", "book": q["book"], "american": int(q["american"]),
                                 "p_model": None if p is None else round(p, 4), "break_even": round(implied_prob(int(q["american"])), 4),
                                 "ev": None if p is None else round(ev_per_unit(p, int(q["american"])), 4), "status": "rejected", "risk": "Excluded",
                                 "reasons": [{"code": "single_model_market", "severity": "exclude",
                                              "text": "Double-double uses one empirical model with no validated cross-check; research display only."}]})
                continue
            proj = project(h, aid, mkt, day, g.season, ctx)
            proj_cache[(gid, aid, mkt)] = (proj, ctx, g)
            if not proj.ok:
                for _, q in grp.iterrows():
                    rows.append({**base, "line": q["line"], "side": q["side"], "kind": q["kind"], "book": q["book"],
                                 "american": int(q["american"]), "status": "rejected", "risk": "Excluded",
                                 "reasons": [{"code": "insufficient_history", "severity": "exclude", "text": proj.reason}]})
                continue
            pairs = {}
            for _, q in grp.iterrows():
                pairs.setdefault((q["kind"], q["line"], q["book"]), {})[q["side"]] = q
            anchors = {}  # book -> (main line, no-vig P(over)) used to price that book's alternate lines
            for (kind, line, book), sd in pairs.items():
                # order_only pairs are near pick'em by construction (|p_over - p_under| < 0.03), so a swapped
                # label moves the anchor by at most ~0.015: acceptable for pricing alternates, never for qualifying.
                if kind == "main" and "over" in sd and "under" in sd and sd["over"]["side_verification"] != "contradicted":
                    anchors[book] = (float(line), no_vig_two_way(int(sd["over"]["american"]), int(sd["under"]["american"]))[0])
            for (kind, line, book), sides in pairs.items():
                cov["main_props" if kind == "main" else "alt_props"] += 1
                for side, q in sides.items():
                    other = sides.get("under" if side == "over" else "over")
                    flags = player_flags(proj, inj["status"] if inj else None, q["side_verification"], kind)
                    if q["retrieved_at"] < stale_cut:
                        flags.append({"code": "stale_odds", "severity": "exclude",
                                      "text": f"Quote retrieved {q['retrieved_at']:%H:%M} UTC, older than {s.odds_stale_after_min} min."})
                    if inj_at is None or (now - inj_at) > timedelta(minutes=s.injuries_stale_after_min):
                        flags.append({"code": "stale_injuries", "severity": "exclude", "text": "Injury report missing or stale."})
                    if g.spread_home is None:
                        flags.append({"code": "no_game_lines", "severity": "caution", "text": "No spread/total available: game script modeled with a wider margin distribution."})
                    if not gate.validated:
                        flags.append({"code": "validation_gate", "severity": "gate", "text": gate.reason})
                    ev = evaluate_quote(proj, float(line), side, int(q["american"]), None if other is None else int(other["american"]),
                                        gate, flags, anchor=anchors.get(book) if kind == "alt" else None,
                                        calibrate=kind == "main")
                    row = {**base, "line": float(line), "side": side, "kind": kind, "book": book, "american": int(q["american"]),
                           "open_line": q["open_line"], "open_american": None if pd.isna(q["open_american"]) else int(q["open_american"]),
                           "first_seen_american": None if pd.isna(q["first_seen_american"]) else int(q["first_seen_american"]),
                           "retrieved_at": q["retrieved_at"], "quote_updated_at": q["quote_updated_at"], "source": q["source"],
                           "source_url": q["source_url"], "side_verification": q["side_verification"],
                           "projection_mean": round(float(proj.mu_grid.mean()), 2), "minutes_proj": round(proj.minutes_mean, 1),
                           **{k: ev[k] for k in ("p_model", "p_empirical", "p_final", "p_conservative", "p_sd", "p_interval", "p_push",
                                                 "p_market_novig", "overround", "break_even", "edge_vs_market", "ev", "ev_conservative",
                                                 "model_disagreement", "outlier_dependence", "blend_weight", "market_basis")},
                           "fair_american": fair_american(ev["p_final"]), "reasons": ev["flags"]}
                    excl = [f for f in ev["flags"] if f["severity"] == "exclude"]
                    row["risk"] = risk_class(ev["flags"], ev["p_sd"], proj.diagnostics.get("minutes_cv", 1))
                    row["status"] = "rejected" if excl else "candidate"
                    rows.append(row)
                    if not excl:
                        candidates.append({"row": row, "eval": ev, "athlete_id": aid, "game_id": gid, "key": (gid, aid, mkt)})

    # Stress-test survivors (most expensive step, so only here)
    survivors = []
    for c in sorted(candidates, key=lambda c: c["eval"]["ev_conservative"], reverse=True)[:40]:
        proj, ctx, g = proj_cache[c["key"]]
        st = stress_test(lambda ov: project(h, c["athlete_id"], c["row"]["market"], day, g.season, ctx, overrides=ov,
                                            B=80, S=200), {**c["eval"]})
        sf = stress_flags(st, c["eval"])
        c["row"]["stress"] = st
        c["row"]["reasons"] = c["row"]["reasons"] + sf
        if any(f["severity"] == "exclude" for f in sf):
            c["row"]["status"], c["row"]["risk"] = "rejected", "Excluded"
            continue
        survivors.append(c)
    for c in candidates[40:]:
        pass
    top = pick_top(survivors, 3)
    shortlisted_ids = set()
    published = []
    for rank, c in enumerate(top, 1):
        r = c["row"]
        proj, ctx, g = proj_cache[c["key"]]
        r["rank"] = rank
        r["status"] = "qualified" if gate.validated else "research_only"
        r["history"] = _history_payload(h, c["athlete_id"], r["market"], day, r["line"], ctx.opp_team_id, teams)
        r["distribution"] = proj.summary_dist(get_settings().mc_seed)
        r["diagnostics"] = _jsonable(proj.diagnostics)
        r["context"] = _context_payload(h, g, ctx, teams, injuries, day)
        r["market_compare"] = [_slim(x) for x in rows if x["athlete_id"] == c["athlete_id"] and x["market"] == r["market"]
                               and x["game_id"] == c["game_id"]]
        r["shared_risk"] = [o["row"]["athlete_name"] for o in top if o is not c and o["game_id"] == c["game_id"]]
        r["sources"] = _sources(r, injuries.get(c["athlete_id"]))
        r["injury_signature"] = _injury_signature(injuries, {ctx.team_id, ctx.opp_team_id})
        shortlisted_ids.add(id(r))
        published.append(r)
    for r in rows:
        if r["status"] == "candidate":
            r["status"] = "passed_filters_not_ranked"
    _publish(slate, run_id, published)

    n_quotes = len(rows)
    rej = defaultdict(int)
    for r in rows:
        for f in r.get("reasons", []):
            if f["severity"] == "exclude":
                rej[f["code"]] += 1
    with session() as ss:
        last_run = ss.scalars(select(ModelRun).where(ModelRun.status == "ok").order_by(ModelRun.run_id.desc())).first()
        fails = ss.scalars(select(FetchLog).where(FetchLog.at >= now - timedelta(hours=1), FetchLog.ok.is_(False))).all()
    cov_out = []
    for g in games:
        c = coverage.get(g.game_id)
        cov_out.append({"game_id": g.game_id, "matchup": f"{teams.get(g.away_team_id)} @ {teams.get(g.home_team_id)}",
                        "start": g.start_time, "status": g.status, "spread_home": g.spread_home, "total": g.total,
                        "evaluated": g in pre_games, "main_props": c["main_props"] if c else 0, "alt_props": c["alt_props"] if c else 0,
                        "players": len(c["players"]) if c else 0,
                        "books": sorted(quotes[quotes["game_id"] == g.game_id]["book"].unique().tolist()) if not quotes.empty else []})
    missing = []
    if not get_settings().odds_api_key:
        missing.append("Only DraftKings (via ESPN) is covered. FanDuel/BetMGM/Caesars need an ODDS_API_KEY.")
    else:
        oa = (refresh_report or {}).get("odds_api") or {}
        if oa.get("skipped"):
            missing.append(f"The Odds API not pulled this refresh: {oa['skipped']}. Its earlier quotes count as stale after {get_settings().odds_stale_after_min} min.")
        if oa.get("games_skipped_budget"):
            missing.append(f"The Odds API: {oa['games_skipped_budget']} game(s) skipped to stay above the credit reserve.")
        if oa.get("errors"):
            missing += [f"The Odds API error: {x}" for x in oa["errors"]]
    missing.append("Steals, blocks, steals+blocks and turnovers props are not on the ESPN feed today; they are modeled only when a provider supplies them.")
    missing.append("Confirmed starting lineups are not available pregame from these sources; role is inferred from recent starts.")
    missing += [f"{c['matchup']}: no DraftKings prop board posted yet" for c in cov_out if c["evaluated"] and c["main_props"] == 0]
    if started_games:
        missing.append(f"{len(started_games)} game(s) already started or final: not evaluated as pregame candidates.")
    overview = {
        "slate_date": slate, "timezone": get_settings().timezone, "generated_at": now, "run_id": run_id,
        "n_games": len(games), "n_games_evaluated": len(pre_games),
        "n_players": len({r["athlete_id"] for r in rows}), "n_props": len({(r["game_id"], r["athlete_id"], r["market"], r["line"], r["kind"]) for r in rows}),
        "n_offers": n_quotes, "n_qualifying": sum(1 for r in published if r["status"] == "qualified"),
        "n_passed_filters": len(survivors), "books": sorted(quotes["book"].unique().tolist()) if not quotes.empty else [],
        "odds_freshest": quotes["retrieved_at"].max() if not quotes.empty else None,
        "odds_oldest": quotes["retrieved_at"].min() if not quotes.empty else None,
        "injury_report_at": inj_at, "injury_source": "ESPN injuries feed (official NBA PDF report is blocked for automated access)",
        "last_successful_run": last_run.finished_at if last_run else None,
        "validation": {"validated": gate.validated, "reason": gate.reason, "blend_weight": gate.blend_weight, "min_edge": gate.min_edge,
                       "calibration": list(gate.calib),
                       "report_generated_at": report.get("generated_at") if report else None},
        "headline": None if any(r["status"] == "qualified" for r in published) else "NO QUALIFYING PICKS TODAY: INSUFFICIENT STATISTICAL EDGE.",
        "rejection_counts": dict(sorted(rej.items(), key=lambda kv: -kv[1])),
        "coverage": cov_out, "missing_coverage": missing, "refresh": refresh_report,
        "recent_fetch_failures": [{"source": f.source, "status": f.status, "url": f.url[:120], "at": f.at} for f in fails[-10:]],
        "paper_mode": True, "model_version": MODEL_VERSION,
    }
    return {"overview": overview, "candidates": published, "slate": [_slim(r) for r in rows]}


def _slim(r: dict) -> dict:
    keep = ("game_id", "athlete_id", "athlete_name", "team", "opp", "matchup", "market", "market_label", "line", "side", "kind",
            "book", "american", "open_line", "open_american", "first_seen_american", "p_model", "p_empirical", "p_final",
            "p_conservative", "p_sd", "p_market_novig", "break_even", "ev", "ev_conservative", "edge_vs_market", "risk", "status",
            "reasons", "projection_mean", "minutes_proj", "side_verification", "retrieved_at", "game_start", "model_disagreement",
            "fair_american", "source", "market_basis")
    return {k: r.get(k) for k in keep}


def _clean(x):
    """Recursively make a payload strict-JSON safe: NaN/inf -> None, numpy scalars -> Python."""
    if isinstance(x, dict):
        return {k: _clean(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_clean(v) for v in x]
    if isinstance(x, np.ndarray):
        return _clean(x.tolist())
    if hasattr(x, "item") and not isinstance(x, (str, bytes)):
        try:
            x = x.item()
        except (ValueError, AttributeError):
            pass
    if isinstance(x, float) and not np.isfinite(x):
        return None
    if x is pd.NaT:
        return None
    return x


def _jsonable(x):
    return json.loads(json.dumps(x, default=lambda o: o.item() if hasattr(o, "item") else str(o)))


def _context_payload(h: History, g, ctx: GameContext, teams, injuries, day) -> dict:
    tp, op = h.team_pace(ctx.team_id, day), h.team_pace(ctx.opp_team_id, day)
    def defense(team):
        t = h.team_games_before(team, day).tail(15)
        if t.empty:
            return None
        poss = t["possessions"].sum()
        opp_rows = h.team_logs[h.team_logs["game_id"].isin(t["game_id"]) & (h.team_logs["team_id"] != team)]
        return {"games": int(len(t)), "def_rating": round(float(t["opp_pts"].sum() / poss * 100), 1),
                "off_rating": round(float(t["pts"].sum() / poss * 100), 1),
                "opp_reb_per100": round(float(opp_rows["reb"].sum() / max(opp_rows["possessions"].sum(), 1) * 100), 1),
                "opp_ast_per100": round(float(opp_rows["ast"].sum() / max(opp_rows["possessions"].sum(), 1) * 100), 1),
                "opp_3pa_per100": round(float(opp_rows["fg3a"].sum() / max(opp_rows["possessions"].sum(), 1) * 100), 1),
                "opp_3pm_per100": round(float(opp_rows["fg3m"].sum() / max(opp_rows["possessions"].sum(), 1) * 100), 1),
                "forced_tov_per100": round(float(opp_rows["tov"].sum() / max(opp_rows["possessions"].sum(), 1) * 100), 1)}
    implied = None
    if g.total is not None and ctx.spread_for_team is not None:
        implied = round(g.total / 2 - ctx.spread_for_team / 2, 1)
    rel = lambda team: [{"name": i["name"], "status": i["status"], "comment": i["comment"], "athlete_id": a}
                        for a, i in injuries.items() if i["team_id"] == team]
    return {"home": ctx.home, "spread_for_team": ctx.spread_for_team, "game_total": g.total, "implied_team_total": implied,
            "back_to_back": ctx.b2b, "team_pace": None if tp is None else round(tp, 1), "opp_pace": None if op is None else round(op, 1),
            "expected_possessions": None if (tp is None or op is None) else round((tp + op) / 2, 1),
            "opponent": defense(ctx.opp_team_id), "team": defense(ctx.team_id),
            "team_injuries": rel(ctx.team_id), "opp_injuries": rel(ctx.opp_team_id),
            "known_out_teammates": [injuries[a]["name"] for a in ctx.known_out_teammates if a in injuries]}


def _sources(r: dict, inj: dict | None) -> list[dict]:
    src = [{"label": "DraftKings prop board (via ESPN)", "url": r.get("source_url"), "retrieved_at": r.get("retrieved_at")},
           {"label": "Game log (ESPN box scores)", "url": f"https://www.espn.com/nba/player/gamelog/_/id/{r['athlete_id']}", "retrieved_at": None},
           {"label": "ESPN injuries feed", "url": "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/injuries",
            "retrieved_at": None}]
    if inj:
        src[-1]["retrieved_at"] = inj.get("reported_at")
    return src


def _publish(slate: str, run_id: int, published: list[dict]):
    """Insert-only. A prediction already stored for the same key is never overwritten."""
    with session() as s:
        for r in published:
            if r["game_start"] <= utcnow():
                continue
            exists = s.scalar(select(Prediction.id).where(
                Prediction.slate_date == slate, Prediction.game_id == r["game_id"], Prediction.athlete_id == r["athlete_id"],
                Prediction.market == r["market"], Prediction.line == r["line"], Prediction.side == r["side"],
                Prediction.book == r["book"], Prediction.model_version == MODEL_VERSION))
            if exists:
                r["prediction_id"] = exists
                continue
            p = Prediction(run_id=run_id, slate_date=slate, game_id=r["game_id"], game_start=r["game_start"], athlete_id=r["athlete_id"],
                           athlete_name=r["athlete_name"], team_abbr=r["team"], opp_abbr=r["opp"], market=r["market"], line=r["line"],
                           side=r["side"], book=r["book"], american=r["american"], p_model=r["p_final"], p_conservative=r["p_conservative"],
                           p_market_novig=r.get("p_market_novig"), ev_per_unit=r["ev"], status=r["status"], model_version=MODEL_VERSION,
                           snapshot=_jsonable(_clean({k: v for k, v in r.items() if k not in ("market_compare",)})))
            s.add(p)
            s.flush()
            r["prediction_id"] = p.id
        s.commit()


def invalidate(slate: str, result: dict):
    """Flag (never edit) published predictions when material information changes before tip-off."""
    injuries, _ = latest_injuries()
    cur = {(r["game_id"], r["athlete_id"], r["market"], r["side"], r["book"]): r for r in result["slate"] if r.get("kind") == "main"}
    with session() as s:
        preds = s.scalars(select(Prediction).where(Prediction.slate_date == slate, Prediction.invalidated_at.is_(None))).all()
        for p in preds:
            if p.game_start <= utcnow():
                continue
            reasons = []
            snap = p.snapshot or {}
            st = injuries.get(p.athlete_id, {}).get("status")
            if st and st.lower() != "active":
                reasons.append(f"Player now listed '{st}'.")
            ctx = snap.get("context") or {}
            team_ids = set()
            g = s.get(Game, p.game_id)
            if g:
                team_ids = {g.home_team_id, g.away_team_id}
            if snap.get("injury_signature") and team_ids and _injury_signature(injuries, team_ids) != snap["injury_signature"]:
                reasons.append("Injury report for this game changed after publication.")
            q = cur.get((p.game_id, p.athlete_id, p.market, p.side, p.book))
            if q is None:
                reasons.append("Quote no longer offered at this line.")
            elif q["line"] != p.line:
                reasons.append(f"Line moved from {p.line} to {q['line']}.")
            elif q.get("ev_conservative") is not None and q["ev_conservative"] <= 0:
                reasons.append(f"Conservative EV is now {q['ev_conservative']:+.3f} at {q['american']:+d}.")
            if reasons:
                p.invalidated_at = utcnow()
                p.invalidation_reason = " ".join(reasons)
        s.commit()


def settle_predictions():
    h = None
    with session() as s:
        open_preds = s.scalars(select(Prediction).where(Prediction.result.is_(None))).all()
        for p in open_preds:
            g = s.get(Game, p.game_id)
            if not g or not g.box_loaded:
                continue
            if h is None:
                h = History()
            row = h.logs[(h.logs["game_id"] == p.game_id) & (h.logs["athlete_id"] == p.athlete_id)]
            close = s.scalars(select(OddsSnapshot).where(
                OddsSnapshot.game_id == p.game_id, OddsSnapshot.athlete_id == p.athlete_id, OddsSnapshot.market == p.market,
                OddsSnapshot.side == p.side, OddsSnapshot.book == p.book, OddsSnapshot.kind == "main",
                OddsSnapshot.retrieved_at <= p.game_start).order_by(OddsSnapshot.retrieved_at.desc())).first()
            if close:
                p.closing_line, p.closing_american = close.line, close.american
            if row.empty or bool(row["dnp"].iloc[0]) or float(row["minutes"].iloc[0]) <= 0:
                p.result, p.actual_value = "void", None
            else:
                comps = STAT_COMPONENTS.get(p.market)
                if p.market == "dd":
                    cats = [int(row[c].iloc[0]) for c in ("pts", "reb", "ast", "stl", "blk")]
                    val = float(sum(1 for c in cats if c >= 10) >= 2)
                else:
                    val = float(sum(int(row[c].iloc[0]) for c in comps))
                p.actual_value = val
                p.result = settle(val, p.line, p.side)
            p.settled_at = utcnow()
        s.commit()


def tracker_summary() -> dict:
    from .odds import profit_if
    with session() as s:
        preds = s.scalars(select(Prediction).order_by(Prediction.game_start)).all()
    rows, eq, units, peak, mdd = [], [], 0.0, 0.0, 0.0
    cal = []
    for p in preds:
        prof = profit_if(p.result, p.american, get_settings().paper_stake_units) if p.result in ("win", "loss", "push", "void") else None
        if prof is not None:
            units += prof
            peak = max(peak, units)
            mdd = max(mdd, peak - units)
            eq.append({"date": p.slate_date, "units": round(units, 3)})
            if p.result in ("win", "loss"):
                cal.append((p.p_model, 1.0 if p.result == "win" else 0.0))
        clv = None
        if p.closing_american is not None and p.closing_line == p.line:
            clv = round(implied_prob(p.closing_american) - implied_prob(p.american), 4)
        rows.append({"id": p.id, "date": p.slate_date, "player": p.athlete_name, "team": p.team_abbr, "opp": p.opp_abbr,
                     "market": MARKET_LABEL.get(p.market, p.market), "side": p.side, "line": p.line, "book": p.book,
                     "american": p.american, "p_model": p.p_model, "p_conservative": p.p_conservative, "status": p.status,
                     "model_version": p.model_version, "created_at": p.created_at, "game_start": p.game_start,
                     "invalidated_at": p.invalidated_at, "invalidation_reason": p.invalidation_reason,
                     "closing_line": p.closing_line, "closing_american": p.closing_american, "clv_implied": clv,
                     "actual": p.actual_value, "result": p.result, "paper_profit": None if prof is None else round(prof, 3)})
    settled = [r for r in rows if r["result"] in ("win", "loss")]
    calib = []
    if cal:
        arr = np.array(cal)
        for lo, hi in ((0, .55), (.55, .6), (.6, .65), (.65, 1.01)):
            m = (arr[:, 0] >= lo) & (arr[:, 0] < hi)
            if m.sum():
                calib.append({"bin": f"{lo:.2f}-{min(hi,1):.2f}", "n": int(m.sum()), "predicted": round(float(arr[m, 0].mean()), 3),
                              "observed": round(float(arr[m, 1].mean()), 3)})
    roll = []
    res = [1.0 if r["result"] == "win" else 0.0 for r in settled]
    for i in range(len(res)):
        w = res[max(0, i - 19): i + 1]
        roll.append({"n": i + 1, "rolling_hit_rate_20": round(float(np.mean(w)), 3)})
    return {"rows": rows[::-1], "n": len(rows), "settled": len(settled),
            "wins": sum(1 for r in settled if r["result"] == "win"), "units": round(units, 3), "max_drawdown": round(mdd, 3),
            "equity": eq, "calibration": calib, "rolling": roll,
            "note": "Paper tracking only, 1 unit per published candidate, including research-only candidates."}


def run_async(slate: str | None = None, refresh: bool = True) -> bool:
    if not _lock.acquire(blocking=False):
        return False
    def work():
        state.update(running=True, last_started=utcnow(), last_error=None)
        try:
            evaluate(slate or today_slate(), refresh=refresh)
        except Exception as e:
            log.exception("pipeline failed")
            state["last_error"] = repr(e)
        finally:
            state["running"] = False
            _lock.release()
    threading.Thread(target=work, daemon=True).start()
    return True
