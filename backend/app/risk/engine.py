"""Risk-averse qualification, stress testing and ranking.

Every rejection carries a machine code and a sentence. Nothing here is a 'confidence score':
the ranking key is the conservative expected value per unit staked, which is an EV computed
with a deliberately pessimistic probability, and every input to it is displayed.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from ..config import get_settings
from ..models.engine import Projection
from ..odds import ev_per_unit, implied_prob, no_vig_two_way

STRESS_SCENARIOS = [
    ("minutes_down_10", "Minutes 10% below projection", {"minutes_mult": 0.90}),
    ("usage_down_10", "Usage / per-minute production 10% lower", {"rate_mult": 0.90}),
    ("efficiency_regress", "Scoring efficiency regresses (points rate -7%)", {"efficiency_regress": True}),
    ("pace_slow", "Game pace 4% slower", {"pace_mult": 0.96}),
    ("blowout", "Game becomes a blowout (25-point margin)", {"force_blowout": True}),
    ("teammate_returns", "Absent teammate unexpectedly plays", {"teammate_returns": True}),
    ("opp_defense_better", "Opponent defends better than its recent sample", {"opp_defense_better": True}),
    ("no_overtime", "Game cannot reach overtime", {"no_overtime": True}),
]


@dataclass
class Gate:
    validated: bool
    blend_weight: float  # weight on the (calibrated) model vs the no-vig market probability
    min_edge: float
    reason: str
    calib: tuple[float, float] = (0.0, 1.0)  # P(over) -> sigmoid(a + b*logit(P(over))), fit walk-forward


def calibrate_side(p: float | None, side: str, calib: tuple[float, float]) -> float | None:
    """Apply the over-probability recalibration map to either side."""
    if p is None:
        return None
    a, b = calib
    q = p if side == "over" else 1 - p
    q = min(max(q, 1e-4), 1 - 1e-4)
    z = a + b * math.log(q / (1 - q))
    qc = 1 / (1 + math.exp(-z))
    return qc if side == "over" else 1 - qc


def side_probs(proj: Projection, line: float, side: str) -> dict:
    pr = proj.probs(line)
    draws = pr["p_over_draws"] if side == "over" else pr["p_under_draws"]
    emp = proj.emp_probs(line)
    p_m1 = pr["p_over"] if side == "over" else pr["p_under"]
    p_m2 = None if emp is None else (emp["p_over"] if side == "over" else emp["p_under"])
    return {"p_m1": p_m1, "p_m2": p_m2, "p_push": pr["p_push"], "p_sd": float(np.std(draws)),
            "p_p10": float(np.percentile(draws, 10)), "p_p90": float(np.percentile(draws, 90)),
            "disagreement": None if p_m2 is None else abs(p_m1 - p_m2)}


def outlier_dependence(proj: Projection, line: float, side: str) -> float | None:
    """How much the empirical probability falls when the two most favorable past games are removed."""
    if proj.emp_values is None or len(proj.emp_values) < 10:
        return None
    v, w = proj.emp_values, proj.emp_weights
    order = np.argsort(v) if side == "under" else np.argsort(-v)
    keep = np.ones(len(v), bool)
    keep[order[:2]] = False
    def p(vv, ww):
        ww = ww / ww.sum()
        return float(ww[vv > line].sum()) if side == "over" else float(ww[vv < line].sum())
    return p(v, w) - p(v[keep], w[keep])


def evaluate_quote(proj: Projection, line: float, side: str, american: int, other_american: int | None,
                   gate: Gate, flags_in: list[dict], anchor: tuple[float, float] | None = None,
                   calibrate: bool = True) -> dict:
    """calibrate=False for alternate lines: the recalibration map was fit on main lines only and is
    not valid in the tails (extrapolating a shallow slope would inflate long-shot probabilities)."""
    """anchor = (main_line, no-vig P(over main_line)) for one-sided alternate lines."""
    s = get_settings()
    sp = side_probs(proj, line, side)
    p_nv = None
    overround = None
    market_basis = "none"
    if other_american is not None:
        p_nv, overround = no_vig_two_way(american, other_american)
        market_basis = "two-way no-vig"
    elif anchor is not None and side == "over":
        p_nv = proj.anchored_over(anchor[0], anchor[1], line)
        market_basis = "anchored to main line" if p_nv is not None else "none"
    w = gate.blend_weight if p_nv is not None else 1.0
    cal = lambda p: calibrate_side(p, side, gate.calib) if calibrate and side in ("over", "under") else p
    p_model = cal(sp["p_m1"])
    p_final = w * p_model + (1 - w) * p_nv if p_nv is not None else p_model
    p_cons_model = cal(min(sp["p_p10"], sp["p_m2"]) if sp["p_m2"] is not None else sp["p_p10"])
    p_cons = w * p_cons_model + (1 - w) * p_nv if p_nv is not None else p_cons_model
    be = implied_prob(american)
    ev = ev_per_unit(p_final, american, sp["p_push"])
    ev_cons = ev_per_unit(p_cons, american, sp["p_push"])
    flags = list(flags_in)
    if sp["p_sd"] > s.max_prob_sd:
        flags.append({"code": "uncertain_probability", "severity": "exclude",
                      "text": f"Probability uncertainty too high (sd {sp['p_sd']:.3f} > {s.max_prob_sd})."})
    if sp["disagreement"] is None:
        flags.append({"code": "no_second_model", "severity": "exclude", "text": "Empirical cross-check unavailable (too few games >= 10 minutes)."})
    elif sp["disagreement"] > s.max_model_disagreement:
        flags.append({"code": "model_disagreement", "severity": "exclude",
                      "text": f"Models disagree by {sp['disagreement']:.3f} (limit {s.max_model_disagreement})."})
    od = outlier_dependence(proj, line, side)
    if od is not None and od > 0.12:
        flags.append({"code": "outlier_dependence", "severity": "exclude",
                      "text": f"Removing the two most favorable past games cuts the empirical probability by {od:.2f}."})
    if p_nv is None and not gate.validated:
        flags.append({"code": "no_market_reference", "severity": "exclude",
                      "text": "No two-way or anchored market probability for this line; the EV shown is the unvalidated "
                              "model's alone and should not be read as an edge."})
    if ev_cons <= gate.min_edge:
        flags.append({"code": "negative_conservative_ev", "severity": "exclude",
                      "text": f"Conservative EV {ev_cons:+.3f}/unit does not clear the {gate.min_edge:+.3f} threshold."})
    if ev <= 0:
        flags.append({"code": "negative_ev", "severity": "exclude", "text": f"Point-estimate EV {ev:+.3f}/unit is not positive."})
    return {"line": line, "side": side, "american": american, "other_american": other_american,
            "p_model": round(p_model, 4), "p_model_raw": round(sp["p_m1"], 4), "p_empirical": None if sp["p_m2"] is None else round(sp["p_m2"], 4),
            "p_final": round(p_final, 4), "p_conservative": round(p_cons, 4), "p_sd": round(sp["p_sd"], 4),
            "p_interval": [round(sp["p_p10"], 4), round(sp["p_p90"], 4)], "p_push": round(sp["p_push"], 4),
            "p_market_novig": None if p_nv is None else round(p_nv, 4),
            "overround": None if overround is None else round(overround, 4), "break_even": round(be, 4),
            "edge_vs_market": None if p_nv is None else round(p_final - p_nv, 4),
            "ev": round(ev, 4), "ev_conservative": round(ev_cons, 4), "blend_weight": w,
            "model_disagreement": None if sp["disagreement"] is None else round(sp["disagreement"], 4), "market_basis": market_basis,
            "outlier_dependence": None if od is None else round(od, 4), "flags": flags}


def player_flags(proj: Projection, injury_status: str | None, side_verification: str, kind: str) -> list[dict]:
    s = get_settings()
    d = proj.diagnostics
    f = []
    if injury_status and injury_status.lower() not in ("active",):
        f.append({"code": "availability", "severity": "exclude",
                  "text": f"Player listed '{injury_status}' on the latest injury report: availability unresolved."})
    if d.get("n_current", 0) < s.min_games_current_season:
        f.append({"code": "small_sample", "severity": "exclude",
                  "text": f"Only {d.get('n_current')} current-season games (need {s.min_games_current_season})."})
    cv = d.get("minutes_cv", 0)
    if cv > s.max_minutes_cv:
        f.append({"code": "minutes_volatile", "severity": "exclude", "text": f"Minutes too volatile (CV {cv:.2f} > {s.max_minutes_cv})."})
    elif cv > 0.15:
        f.append({"code": "minutes_moderate", "severity": "caution", "text": f"Minutes moderately variable (CV {cv:.2f})."})
    ss = d.get("starter_share_l5", 1.0)
    if 0.2 < ss < 0.8:
        f.append({"code": "role_flux", "severity": "exclude", "text": f"Started {ss:.0%} of the last 5 games: role in flux."})
    l5 = d.get("minutes_l5") or []
    if l5 and d.get("minutes_recent"):
        rel = abs(np.mean(l5) - d["minutes_recent"]) / max(d["minutes_recent"], 1)
        if rel > 0.20:
            f.append({"code": "recent_role_change", "severity": "exclude",
                      "text": f"Last-5 minutes ({np.mean(l5):.1f}) differ from the projection base by {rel:.0%}."})
    if any(t.get("applied") and abs(t.get("rate_ratio_raw", 1) - 1) > 0.10 for t in d.get("teammate_adjustments", [])):
        f.append({"code": "absence_dependent", "severity": "caution",
                  "text": "Projection includes a usage shift from an absent teammate (small with/without sample)."})
    if side_verification == "contradicted":
        f.append({"code": "side_contradicted", "severity": "exclude", "text": "Over/under order contradicted by the alternate-line ladder."})
    elif side_verification == "order_only":
        f.append({"code": "side_unverified", "severity": "exclude",
                  "text": "Over/under labels inferred from feed order only (no ladder cross-check possible)."})
    if kind == "alt":
        f.append({"code": "alt_line_unvalidated", "severity": "exclude",
                  "text": "Alternate line: one-sided market (market probability only anchored to the main line) and not "
                          "covered by the walk-forward validation, which uses main lines. Research display only."})
    if d.get("p_overtime", 0) > 0.1:
        f.append({"code": "overtime_exposure", "severity": "caution", "text": "Elevated overtime probability in this matchup."})
    return f


def stress_test(project_fn, base: dict) -> dict:
    """project_fn(overrides) -> Projection. Returns per-scenario probability changes for the side."""
    out = []
    worst = base["p_model"]
    for code, label, ov in STRESS_SCENARIOS:
        pj = project_fn(ov)
        if not pj.ok:
            continue
        sp = side_probs(pj, base["line"], base["side"])
        out.append({"code": code, "label": label, "p": round(sp["p_m1"], 4), "delta": round(sp["p_m1"] - base["p_model"], 4),
                    "ev": round(ev_per_unit(sp["p_m1"], base["american"], sp["p_push"]), 4)})
        worst = min(worst, sp["p_m1"])
    # market moves: line one point against, price 15 cents worse
    pj = project_fn({})
    bad_line = base["line"] + (1 if base["side"] == "over" else -1)
    sp = side_probs(pj, bad_line, base["side"])
    out.append({"code": "line_moves_against", "label": f"Line moves 1 point against (to {bad_line})", "p": round(sp["p_m1"], 4),
                "delta": round(sp["p_m1"] - base["p_model"], 4), "ev": round(ev_per_unit(sp["p_m1"], base["american"], sp["p_push"]), 4)})
    a = base["american"]
    worse = a - 15 if a < 0 else (a - 15 if a - 15 >= 100 else -100 - (15 - (a - 100)))
    out.append({"code": "odds_worse", "label": f"Price worsens to {worse:+d}", "p": base["p_model"], "delta": 0.0,
                "ev": round(ev_per_unit(base["p_final"], worse, base["p_push"]), 4)})
    deltas = sorted([o for o in out if o["code"] not in ("odds_worse",)], key=lambda o: o["delta"])
    return {"scenarios": out, "worst_p": round(worst, 4), "most_sensitive": [o["code"] for o in deltas[:3]],
            "n_scenarios_below_break_even": sum(1 for o in out if o["p"] < base["break_even"])}


def stress_flags(st: dict, base: dict) -> list[dict]:
    f = []
    by = {o["code"]: o for o in st["scenarios"]}
    if "no_overtime" in by and by["no_overtime"]["delta"] < -0.03:
        f.append({"code": "overtime_reliance", "severity": "exclude", "text": "Probability relies on overtime by more than 3 points."})
    if "blowout" in by and by["blowout"]["delta"] < -0.15:
        f.append({"code": "script_dependence", "severity": "exclude",
                  "text": f"A blowout cuts the probability by {-by['blowout']['delta']:.2f}: depends on a competitive game script."})
    if "teammate_returns" in by and by["teammate_returns"]["delta"] < -0.06:
        f.append({"code": "teammate_assumption", "severity": "exclude",
                  "text": "Edge depends on a teammate's absence: a surprise return erases it."})
    if st["n_scenarios_below_break_even"] >= 4:
        f.append({"code": "fragile", "severity": "exclude",
                  "text": f"{st['n_scenarios_below_break_even']} stress scenarios push the probability below break-even."})
    return f


def risk_class(flags: list[dict], p_sd: float, minutes_cv: float) -> str:
    cautions = sum(1 for f in flags if f["severity"] == "caution")
    if any(f["severity"] == "exclude" for f in flags):
        return "Excluded"
    if cautions == 0 and p_sd < 0.04 and minutes_cv < 0.15:
        return "Lower"
    if cautions <= 1 and p_sd < 0.055:
        return "Moderate"
    return "Elevated"


def pick_top(candidates: list[dict], k: int = 3) -> list[dict]:
    """Highest conservative EV first; at most one per player and one per game (avoids shared-risk stacks)."""
    out, players, games = [], set(), set()
    for c in sorted(candidates, key=lambda c: c["eval"]["ev_conservative"], reverse=True):
        if c["athlete_id"] in players or c["game_id"] in games:
            continue
        out.append(c)
        players.add(c["athlete_id"])
        games.add(c["game_id"])
        if len(out) == k:
            break
    return out
