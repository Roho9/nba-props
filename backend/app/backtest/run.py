"""Walk-forward validation.

Two separate questions, reported separately:
  A. Outcome forecasting (no prices): are the model's probabilities calibrated and better than
     simple baselines? Uses last season with proxy thresholds, plus this season's real lines.
  B. Betting strategy (real DraftKings lines this season, as last quoted before tip-off on ESPN):
     would the selection rule have made money out of sample, at the price actually offered?

Leakage controls: every projection uses games strictly before the game date; league parameters
are re-estimated weekly from prior games only; blend weight and edge threshold for week k are
fit on weeks < k only. Teammate absences count as 'known' only if the teammate also missed the
team's previous game (a proxy for what the pregame injury report would have said). Players who
did not play are voided, matching sportsbook settlement.
"""
from __future__ import annotations

import json
import math
import time
from collections import defaultdict
from datetime import date

import numpy as np
import pandas as pd
from sqlalchemy import select

from ..config import BACKEND_DIR
from ..db import BacktestRun, OddsSnapshot, get_engine, session
from ..models.engine import MODEL_VERSION, STAT_COMPONENTS, GameContext, History, project
from ..odds import american_to_decimal, ev_per_unit, implied_prob, no_vig_two_way
from ..risk.engine import Gate, evaluate_quote, pick_top, player_flags

REPORT_PATH = BACKEND_DIR / "data" / "validation_report.json"
RECORDS_PATH = BACKEND_DIR / "data" / "backtest_records.csv"
EXCLUDE_IN_BACKTEST = {"availability"}  # no historical injury reports exist to replay


def _clip(p):
    return np.clip(p, 1e-4, 1 - 1e-4)


def brier(p, y):
    p, y = np.asarray(p, float), np.asarray(y, float)
    return float(np.mean((p - y) ** 2))


def logloss(p, y):
    p, y = _clip(np.asarray(p, float)), np.asarray(y, float)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def calibration(p, y, bins=10):
    p, y = np.asarray(p, float), np.asarray(y, float)
    edges = np.linspace(0, 1, bins + 1)
    rows, ece = [], 0.0
    for i in range(bins):
        m = (p >= edges[i]) & (p < edges[i + 1] if i < bins - 1 else p <= 1)
        if m.sum() == 0:
            continue
        rows.append({"bin": f"{edges[i]:.1f}-{edges[i+1]:.1f}", "n": int(m.sum()), "mean_pred": round(float(p[m].mean()), 4),
                     "observed": round(float(y[m].mean()), 4)})
        ece += m.sum() / len(p) * abs(p[m].mean() - y[m].mean())
    return rows, float(ece)


def bootstrap_ci(x, stat=np.mean, n=2000, seed=7, q=(5, 95)):
    x = np.asarray(x, float)
    if len(x) < 5:
        return [None, None]
    rng = np.random.default_rng(seed)
    vals = [stat(x[rng.integers(0, len(x), len(x))]) for _ in range(n)]
    return [round(float(np.percentile(vals, q[0])), 4), round(float(np.percentile(vals, q[1])), 4)]


def drawdown_stats(profits):
    if not len(profits):
        return 0.0, 0
    eq = np.cumsum(profits)
    peak = np.maximum.accumulate(np.concatenate([[0], eq]))[1:]
    mdd = float((peak - eq).max())
    streak = best = 0
    for p in profits:
        streak = streak + 1 if p < 0 else 0
        best = max(best, streak)
    return mdd, best


def _contexts(h: History, game_id: str) -> dict[str, GameContext]:
    g = h.games.loc[game_id]
    day = int(g["day"])
    out = {}
    for team, opp, home in ((g["home_team_id"], g["away_team_id"], True), (g["away_team_id"], g["home_team_id"], False)):
        spread = None if pd.isna(g["spread_home"]) else (g["spread_home"] if home else -g["spread_home"])
        tl = h.team_logs
        prev = tl[(tl["team_id"] == team) & (tl["day"] < day)].tail(1)
        b2b = bool(len(prev) and int(prev["day"].iloc[0]) == day - 1)
        # known-out proxy: rotation players who missed this game and the team's previous game
        roster = h._by_team_players.get(team)
        known_out = []
        if roster is not None:
            this = roster[roster["game_id"] == game_id]
            missing = set(this[this["dnp"]]["athlete_id"])
            if len(prev):
                pg = prev["game_id"].iloc[0]
                prev_rows = roster[roster["game_id"] == pg]
                prev_played = set(prev_rows[~prev_rows["dnp"]]["athlete_id"])
                season_players = roster[(roster["day"] < day) & (roster["season"] == g["season"])]
                regulars = set(season_players.groupby("athlete_id")["minutes"].mean().loc[lambda s: s >= 24].index)
                present = set(this["athlete_id"])
                for a in regulars:
                    if a not in prev_played and (a in missing or a not in present):
                        known_out.append(a)
        out[team] = GameContext(game_id, team, opp, home, None if spread is None else float(spread),
                                None if pd.isna(g["total"]) else float(g["total"]), known_out, b2b)
    return out


def load_lines(season: int) -> pd.DataFrame:
    with get_engine().connect() as c:
        q = select(OddsSnapshot).where(OddsSnapshot.is_historical_close.is_(True), OddsSnapshot.kind == "main",
                                       OddsSnapshot.side_verification.in_(["ladder_verified", "labeled"]))
        df = pd.read_sql(q, c)
    if df.empty:
        return df
    df = df.sort_values("retrieved_at").drop_duplicates(["game_id", "athlete_id", "market", "side", "book"], keep="last")
    piv = df.pivot_table(index=["game_id", "athlete_id", "market", "line", "book"], columns="side",
                         values=["american", "open_line", "open_american"], aggfunc="first")
    piv.columns = [f"{a}_{b}" for a, b in piv.columns]
    piv = piv.reset_index().dropna(subset=["american_over", "american_under"])
    return piv


def build_records(h: History, season: int, burn_in_days: int = 14, B: int = 60, S: int = 150, progress=print) -> pd.DataFrame:
    lines = load_lines(season)
    if lines.empty:
        return pd.DataFrame()
    lines = lines[lines["game_id"].isin(h.games.index)]
    lines["day"] = h.games.loc[lines["game_id"], "day"].to_numpy()
    first_day = int(h.games[h.games["season"] == season]["day"].min())
    lines = lines[lines["day"] >= first_day + burn_in_days]
    recs = []
    t0 = time.time()
    games = lines["game_id"].unique()
    for gi, gid in enumerate(games):
        ctxs = _contexts(h, gid)
        gl = lines[lines["game_id"] == gid]
        box = h.logs[h.logs["game_id"] == gid].set_index("athlete_id")
        day = int(h.games.loc[gid, "day"])
        for (aid, mkt), grp in gl.groupby(["athlete_id", "market"]):
            if aid not in box.index or mkt not in STAT_COMPONENTS:
                continue
            row = box.loc[aid]
            if bool(row["dnp"]) or row["minutes"] <= 0:
                continue  # void
            ctx = ctxs.get(row["team_id"])
            if ctx is None:
                continue
            proj = project(h, aid, mkt, day, season, ctx, B=B, S=S)
            actual = float(sum(row[c] for c in STAT_COMPONENTS[mkt]))
            hist = h.player_before(aid, day)
            hist = hist[(~hist["dnp"]) & (hist["minutes"] > 0)]
            vals = hist[STAT_COMPONENTS[mkt]].sum(axis=1).to_numpy(float)
            for _, ln in grp.iterrows():
                line = float(ln["line"])
                l10 = vals[-10:]
                base = {"game_id": gid, "date": h.games.loc[gid, "game_date"], "athlete_id": aid, "market": mkt, "line": line,
                        "book": ln["book"], "am_over": int(ln["american_over"]), "am_under": int(ln["american_under"]),
                        "open_line": ln.get("open_line_over"), "open_over": ln.get("open_american_over"),
                        "open_under": ln.get("open_american_under"), "actual": actual, "starter": bool(row["starter"]),
                        "l10_hit": float(((l10 > line).sum() + 1) / (len(l10) + 2)) if len(l10) else 0.5,
                        "p_market_over": no_vig_two_way(int(ln["american_over"]), int(ln["american_under"]))[0]}
                if not proj.ok:
                    recs.append({**base, "model_ok": False, "reason": proj.reason})
                    continue
                pr = proj.probs(line)
                em = proj.emp_probs(line)
                d = {**base, "model_ok": True, "p_m1_over": pr["p_over"], "p_m1_under": pr["p_under"], "p_push": pr["p_push"],
                     "p_m2_over": None if em is None else em["p_over"], "p_m2_under": None if em is None else em["p_under"],
                     "minutes_cv": proj.diagnostics.get("minutes_cv"), "proj_mean": float(proj.mu_grid.mean()),
                     "proj_minutes": proj.diagnostics.get("expected_minutes_after_script"), "actual_minutes": float(row["minutes"])}
                gate = Gate(True, 1.0, -99, "")
                for side in ("over", "under"):
                    am, other = (base["am_over"], base["am_under"]) if side == "over" else (base["am_under"], base["am_over"])
                    flags = [f for f in player_flags(proj, None, "ladder_verified", "main") if f["code"] not in EXCLUDE_IN_BACKTEST]
                    ev = evaluate_quote(proj, line, side, am, other, gate, flags)
                    d[f"p10_{side}"] = ev["p_interval"][0]
                    d[f"psd_{side}"] = ev["p_sd"]
                    d[f"excl_{side}"] = ",".join(sorted({f["code"] for f in ev["flags"] if f["severity"] == "exclude"
                                                        and f["code"] not in ("negative_ev", "negative_conservative_ev")}))
                recs.append(d)
        if gi % 20 == 0:
            progress(f"  backtest game {gi}/{len(games)}  records={len(recs)}  {time.time()-t0:.0f}s")
    return pd.DataFrame(recs)


def _logit(p):
    p = _clip(np.asarray(p, float))
    return np.log(p / (1 - p))


def _apply_cal(p_over, calib):
    a, b = calib
    return 1 / (1 + np.exp(-(a + b * _logit(p_over))))


def _fit_calibration(train: pd.DataFrame) -> tuple[float, float]:
    """Platt-style recalibration of the model's P(over): y ~ sigmoid(a + b*logit(p)). Train folds only."""
    from sklearn.linear_model import LogisticRegression
    t = train[train["actual"] != train["line"]]
    if len(t) < 300:
        return (0.0, 1.0)
    lr = LogisticRegression(C=1e4).fit(_logit(t["p_m1_over"]).reshape(-1, 1), (t["actual"] > t["line"]).astype(int))
    return (float(lr.intercept_[0]), float(lr.coef_[0][0]))


def _side_cal(p, side, calib):
    p = np.asarray(p, float)
    return _apply_cal(p, calib) if side == "over" else 1 - _apply_cal(1 - p, calib)


def _side_rows(df: pd.DataFrame, w: float, calib=(0.0, 1.0)) -> pd.DataFrame:
    """Expand to one row per (prop, side) with calibrated, blended and conservative probabilities."""
    out = []
    for side in ("over", "under"):
        x = df.copy()
        x["side"] = side
        x["american"] = x["am_over"] if side == "over" else x["am_under"]
        x["other"] = x["am_under"] if side == "over" else x["am_over"]
        pm = x["p_market_over"] if side == "over" else 1 - x["p_market_over"]
        x["p_mkt"] = pm
        x["p_model"] = _side_cal(x[f"p_m1_{side}"], side, calib)
        x["p_emp"] = _side_cal(x[f"p_m2_{side}"].fillna(x[f"p_m1_{side}"]), side, calib)
        x["p_final"] = w * x["p_model"] + (1 - w) * pm
        cons_m = np.minimum(_side_cal(x[f"p10_{side}"], side, calib), x["p_emp"])
        x["p_cons"] = w * cons_m + (1 - w) * pm
        x["excl"] = x[f"excl_{side}"]
        x["win"] = (x["actual"] > x["line"]) if side == "over" else (x["actual"] < x["line"])
        x["push"] = x["actual"] == x["line"]
        out.append(x)
    s = pd.concat(out, ignore_index=True)
    dec = s["american"].map(american_to_decimal)
    s["ev"] = s["p_final"] * (dec - 1) - (1 - s["p_final"] - s["p_push"])
    s["ev_cons"] = s["p_cons"] * (dec - 1) - (1 - s["p_cons"] - s["p_push"])
    s["profit"] = np.where(s["push"], 0.0, np.where(s["win"], dec - 1, -1.0))
    return s


def _fit_blend(train: pd.DataFrame, calib=(0.0, 1.0)) -> float:
    y = (train["actual"] > train["line"]).astype(float)
    pc = _apply_cal(train["p_m1_over"], calib)
    best, bw = 9e9, 0.0
    for w in np.linspace(0, 1, 11):
        p = w * pc + (1 - w) * train["p_market_over"]
        ll = logloss(p, y)
        if ll < best - 1e-6:
            best, bw = ll, float(w)
    return bw


def _select(sides: pd.DataFrame, min_edge: float, top3: bool) -> pd.DataFrame:
    c = sides[(sides["excl"] == "") & (sides["ev"] > 0) & (sides["ev_cons"] > min_edge)]
    if not top3 or c.empty:
        return c
    picks = []
    for d, grp in c.groupby("date"):
        cand = [{"athlete_id": r.athlete_id, "game_id": r.game_id, "eval": {"ev_conservative": r.ev_cons}, "idx": i}
                for i, r in grp.iterrows()]
        picks += [p["idx"] for p in pick_top(cand, 3)]
    return c.loc[picks]


def _strategy_summary(bets: pd.DataFrame) -> dict:
    if bets.empty:
        return {"n": 0}
    bets = bets.sort_values("date")
    prof = bets["profit"].to_numpy()
    settled = bets[~bets["push"]]
    mdd, streak = drawdown_stats(prof)
    by_mkt = {m: {"n": int(len(g)), "roi": round(float(g["profit"].mean()), 4), "hit": round(float(g["win"].mean()), 4)}
              for m, g in bets.groupby("market")}
    buckets = pd.cut(bets["p_final"], [0, 0.5, 0.55, 0.6, 0.65, 0.7, 1.0])
    by_prob = {str(k): {"n": int(len(g)), "expected_hit": round(float(g["p_final"].mean()), 4),
                        "realized_hit": round(float(g["win"].mean()), 4), "roi": round(float(g["profit"].mean()), 4)}
               for k, g in bets.groupby(buckets, observed=True)}
    by_role = {("starter" if k else "bench"): {"n": int(len(g)), "roi": round(float(g["profit"].mean()), 4)}
               for k, g in bets.groupby("starter")}
    by_month = {k: {"n": int(len(g)), "roi": round(float(g["profit"].mean()), 4)}
                for k, g in bets.groupby(bets["date"].str[:7])}
    return {"n": int(len(bets)), "pushes": int(bets["push"].sum()),
            "hit_rate": round(float(settled["win"].mean()), 4) if len(settled) else None,
            "expected_hit_rate": round(float(bets["p_final"].mean()), 4),
            "avg_break_even": round(float(bets["american"].map(implied_prob).mean()), 4),
            "roi": round(float(prof.mean()), 4), "roi_ci90": bootstrap_ci(prof), "units": round(float(prof.sum()), 2),
            "max_drawdown_units": round(mdd, 2), "longest_losing_streak": streak, "by_market": by_mkt,
            "by_probability": by_prob, "by_role": by_role, "by_month": by_month,
            "equity_curve": [{"date": d, "units": round(float(u), 3)} for d, u in
                             bets.groupby("date")["profit"].sum().cumsum().items()]}


def walk_forward(records: pd.DataFrame) -> dict:
    df = records[records["model_ok"]].copy()
    if df.empty:
        return {"status": "insufficient_data"}
    df["week"] = pd.to_datetime(df["date"]).dt.to_period("W").astype(str)
    weeks = sorted(df["week"].unique())
    folds, bets_top3, bets_all, oos = [], [], [], []
    for k, wk in enumerate(weeks):
        if k < 1:
            continue  # the first evaluation week only trains the blend
        train, test = df[df["week"] < wk], df[df["week"] == wk]
        calib = _fit_calibration(train)
        w = _fit_blend(train, calib)
        tr_sides = _side_rows(train, w, calib)
        best_edge, best_roi = 0.02, -9e9
        for e in (0.0, 0.01, 0.02, 0.04):
            sel = _select(tr_sides, e, top3=True)
            if len(sel) >= 20 and sel["profit"].mean() > best_roi:
                best_edge, best_roi = e, float(sel["profit"].mean())
        te_sides = _side_rows(test, w, calib)
        b3 = _select(te_sides, best_edge, top3=True)
        ba = _select(te_sides, best_edge, top3=False)
        bets_top3.append(b3)
        bets_all.append(ba)
        t = test.copy()
        t["p_cal_over"] = _apply_cal(t["p_m1_over"], calib)
        t["p_blend_over"] = w * t["p_cal_over"] + (1 - w) * t["p_market_over"]
        oos.append(t)
        folds.append({"week": wk, "train_n": int(len(train)), "test_n": int(len(test)), "blend_weight": w,
                      "calibration": [round(calib[0], 4), round(calib[1], 4)],
                      "min_edge": best_edge, "bets_top3": int(len(b3))})
    if not oos:
        return {"status": "insufficient_data"}
    o = pd.concat(oos)
    o = o[o["actual"] != o["line"]]
    y = (o["actual"] > o["line"]).astype(float).to_numpy()
    probs = {"model_m1": o["p_m1_over"], "model_m1_calibrated_wf": o["p_cal_over"], "model_m2_empirical": o["p_m2_over"].fillna(o["p_m1_over"]),
             "market_no_vig": o["p_market_over"], "blend_walk_forward": o["p_blend_over"],
             "baseline_l10_hit_rate": o["l10_hit"], "baseline_coin_flip": pd.Series(0.5, index=o.index)}
    metrics = {}
    for name, p in probs.items():
        cal, ece = calibration(p.to_numpy(), y)
        metrics[name] = {"brier": round(brier(p, y), 5), "log_loss": round(logloss(p, y), 5), "ece": round(ece, 4),
                         "calibration": cal}
    ll_m = -(y * np.log(_clip(o["p_m1_over"])) + (1 - y) * np.log(_clip(1 - o["p_m1_over"])))
    ll_k = -(y * np.log(_clip(o["p_market_over"])) + (1 - y) * np.log(_clip(1 - o["p_market_over"])))
    ll_b = -(y * np.log(_clip(o["p_blend_over"])) + (1 - y) * np.log(_clip(1 - o["p_blend_over"])))
    ll_c = -(y * np.log(_clip(o["p_cal_over"])) + (1 - y) * np.log(_clip(1 - o["p_cal_over"])))
    imp_model = bootstrap_ci((ll_k - ll_m).to_numpy())
    imp_cal = bootstrap_ci((ll_k - ll_c).to_numpy())
    imp_blend = bootstrap_ci((ll_k - ll_b).to_numpy())
    by_market = {}
    for m, g in o.groupby("market"):
        yy = (g["actual"] > g["line"]).astype(float)
        by_market[m] = {"n": int(len(g)), "brier_model": round(brier(g["p_m1_over"], yy), 5),
                        "brier_market": round(brier(g["p_market_over"], yy), 5),
                        "over_rate": round(float(yy.mean()), 4), "mean_market_over": round(float(g["p_market_over"].mean()), 4)}
    u = o.drop_duplicates(["game_id", "athlete_id", "market"])
    bias = {"minutes_mean_error": round(float((u["proj_minutes"] - u["actual_minutes"]).mean()), 3),
            "minutes_mae": round(float((u["proj_minutes"] - u["actual_minutes"]).abs().mean()), 3),
            "by_market_mean_error": {m: round(float((g["proj_mean"] - g["actual"]).mean()), 3) for m, g in u.groupby("market")},
            "mean_model_minus_market_over": round(float((o["p_m1_over"] - o["p_market_over"]).mean()), 4)}
    s3 = _strategy_summary(pd.concat(bets_top3) if bets_top3 else pd.DataFrame())
    sa = _strategy_summary(pd.concat(bets_all) if bets_all else pd.DataFrame())
    # The rule set: the model must add information beyond the market AND the top-3 rule must
    # show a positive ROI whose 90% bootstrap interval excludes zero on >= 150 out-of-sample bets.
    adds_info = imp_blend[0] is not None and imp_blend[0] > 0
    profitable = s3.get("n", 0) >= 150 and s3.get("roi_ci90", [None])[0] is not None and s3["roi_ci90"][0] > 0
    last = folds[-1] if folds else {"blend_weight": 0.0, "min_edge": 0.02, "calibration": [0.0, 1.0]}
    final_calib = _fit_calibration(df)  # all scored data, for live use from today onward
    reasons = []
    if not adds_info:
        reasons.append("Out-of-sample log loss of the model/market blend is not reliably better than the no-vig market "
                       f"(improvement 90% CI {imp_blend}).")
    if not profitable:
        reasons.append(f"Top-3 selection rule: {s3.get('n', 0)} out-of-sample bets, ROI {s3.get('roi')} "
                       f"(90% CI {s3.get('roi_ci90')}); needs >= 150 bets and a CI above zero.")
    return {"status": "passed" if adds_info and profitable else "failed", "reasons": reasons,
            "n_props_scored": int(len(o)), "weeks": len(weeks), "folds": folds,
            "probability_metrics": metrics, "logloss_improvement_vs_market": {"model_m1": imp_model, "model_m1_calibrated": imp_cal, "blend": imp_blend},
            "by_market": by_market, "projection_bias": bias, "strategy_top3": s3, "strategy_all_qualifying": sa,
            "current_blend_weight": _fit_blend(df, final_calib), "current_min_edge": last["min_edge"],
            "current_calibration": [round(final_calib[0], 4), round(final_calib[1], 4)],
            "date_range": [str(df["date"].min()), str(df["date"].max())]}


def proxy_outcome_validation(h: History, season: int, every_n_days: int = 6, min_mpg: float = 26.0,
                             B: int = 40, S: int = 100, progress=print) -> dict:
    """Outcome-only validation where no lines exist: threshold = player's last-10 mean rounded to .5."""
    G = h.games[(h.games["season"] == season) & h.games["home_score"].notna()].sort_values("day")
    days = sorted(G["day"].unique())
    if len(days) < 40:
        return {"status": "insufficient_data"}
    test_days = days[30::every_n_days]
    recs = []
    for di, day in enumerate(test_days):
        for gid in G[G["day"] == day].index:
            ctxs = _contexts(h, gid)
            box = h.logs[(h.logs["game_id"] == gid) & (~h.logs["dnp"]) & (h.logs["minutes"] > 0)]
            for _, row in box.iterrows():
                hist = h.player_before(row["athlete_id"], day)
                hist = hist[(~hist["dnp"]) & (hist["season"] == season)]
                if len(hist) < 10 or hist["minutes"].tail(10).mean() < min_mpg:
                    continue
                for mkt in ("pts", "reb", "ast", "pra", "fg3m"):
                    vals = hist[STAT_COMPONENTS[mkt]].sum(axis=1).to_numpy(float)
                    line = math.floor(vals[-10:].mean()) + 0.5
                    proj = project(h, row["athlete_id"], mkt, int(day), season, ctxs[row["team_id"]], B=B, S=S)
                    if not proj.ok:
                        continue
                    actual = float(sum(row[c] for c in STAT_COMPONENTS[mkt]))
                    em = proj.emp_probs(line)
                    recs.append({"market": mkt, "y": float(actual > line), "p_m1": proj.probs(line)["p_over"],
                                 "p_m2": em["p_over"] if em else None,
                                 "l10": float(((vals[-10:] > line).sum() + 1) / 12), "l20": float(((vals[-20:] > line).sum() + 1) / (len(vals[-20:]) + 2))})
        if di % 5 == 0:
            progress(f"  proxy validation {season}: day {di}/{len(test_days)} records={len(recs)}")
    df = pd.DataFrame(recs)
    if df.empty:
        return {"status": "insufficient_data"}
    out = {"status": "ok", "season": season, "n": int(len(df)), "threshold_rule": "floor(last-10 mean) + 0.5",
           "note": "No sportsbook lines used. Tests the outcome model only; says nothing about profitability.", "models": {}}
    for name in ("p_m1", "p_m2", "l10", "l20"):
        p = df[name].fillna(df["p_m1"])
        cal, ece = calibration(p.to_numpy(), df["y"].to_numpy())
        out["models"][name] = {"brier": round(brier(p, df["y"]), 5), "log_loss": round(logloss(p, df["y"]), 5),
                               "ece": round(ece, 4), "calibration": cal}
    out["by_market"] = {m: {"n": int(len(g)), "brier_m1": round(brier(g["p_m1"], g["y"]), 5),
                            "brier_l10": round(brier(g["l10"], g["y"]), 5)} for m, g in df.groupby("market")}
    return out


def run(progress=print, proxy: bool = True) -> dict:
    h = History()
    seasons = sorted(h.games["season"].dropna().unique().astype(int))
    cur = seasons[-1]
    progress(f"building out-of-sample records for season {cur}")
    recs = build_records(h, cur, progress=progress)
    if not recs.empty:
        recs.to_csv(RECORDS_PATH, index=False)
    report = {"model_version": MODEL_VERSION, "generated_at": pd.Timestamp.utcnow().isoformat(),
              "data": {"seasons": seasons, "lines_source": "DraftKings via ESPN, last quote before tip-off (historical boards)",
                       "records": int(len(recs))}}
    report["betting_validation"] = walk_forward(recs) if not recs.empty else {"status": "insufficient_data"}
    if proxy and len(seasons) > 1:
        report["outcome_validation_previous_season"] = proxy_outcome_validation(h, seasons[-2], progress=progress)
    report["status"] = report["betting_validation"].get("status", "insufficient_data")
    REPORT_PATH.write_text(json.dumps(report, indent=1, default=str))
    with session() as s:
        s.add(BacktestRun(model_version=MODEL_VERSION, report=json.loads(json.dumps(report, default=str))))
        s.commit()
    return report


def load_report() -> dict | None:
    if REPORT_PATH.exists():
        return json.loads(REPORT_PATH.read_text())
    return None


if __name__ == "__main__":
    import sys
    r = run(proxy="--no-proxy" not in sys.argv)
    bv = r["betting_validation"]
    print(json.dumps({"status": r["status"], "reasons": bv.get("reasons"), "metrics": {k: {kk: v[kk] for kk in ("brier", "log_loss", "ece")}
                      for k, v in bv.get("probability_metrics", {}).items()}, "top3": {k: bv.get("strategy_top3", {}).get(k)
                      for k in ("n", "hit_rate", "roi", "roi_ci90", "max_drawdown_units")}}, indent=1))
