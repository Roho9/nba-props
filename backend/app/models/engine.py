"""Player outcome forecasting.

Primary model (M1, "minutes x rate negative binomial"):
  minutes  ~ Normal(m_hat * b2b * game_script(margin), sd_min), truncated to [0, 53]
  margin   ~ Normal(-spread, sigma_margin)  (game script; drives blowout minute loss and overtime)
  count    ~ NegBinomial(mean = minutes * rate * opp_factor * teammate_factor, dispersion alpha)
  rate     ~ Gamma posterior around a recency-weighted, prior-shrunk per-minute rate
Combination markets (PRA, P+R, ...) are modeled on the summed series itself, so the variance of
the sum comes from the player's observed joint outcomes and the component correlation is kept.

Second model (M2, "empirical minutes-scaled"): recency-weighted empirical distribution of the
player's past outcomes, each rescaled by projected / actual minutes. It shares no distributional
assumption with M1; |M1 - M2| is reported as model disagreement.

Everything here takes an `as_of` date and reads only games strictly before it.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from scipy import stats as sps
from sqlalchemy import select

from ..config import get_settings
from ..db import Game, Player, PlayerGameLog, Team, TeamGameLog, get_engine

MODEL_VERSION = "nb-minutes-rate-1.1"

STAT_COMPONENTS = {
    "pts": ["pts"], "reb": ["reb"], "ast": ["ast"], "fg3m": ["fg3m"], "stl": ["stl"], "blk": ["blk"],
    "tov": ["tov"], "pra": ["pts", "reb", "ast"], "pr": ["pts", "reb"], "pa": ["pts", "ast"],
    "ra": ["reb", "ast"], "stlblk": ["stl", "blk"],
}
MARKET_LABEL = {"pts": "Points", "reb": "Rebounds", "ast": "Assists", "fg3m": "3-Pointers Made", "stl": "Steals",
                "blk": "Blocks", "tov": "Turnovers", "pra": "Pts + Reb + Ast", "pr": "Pts + Reb", "pa": "Pts + Ast",
                "ra": "Reb + Ast", "stlblk": "Steals + Blocks", "dd": "Double-Double"}
POS_GROUP = {"PG": "G", "SG": "G", "G": "G", "SF": "F", "PF": "F", "F": "F", "C": "C", "FC": "C", "GF": "F"}

RATE_PRIOR_MIN = 120.0  # pseudo-minutes of shrinkage toward the prior per-minute rate
MIN_HALFLIFE_GAMES = 6.0
RATE_HALFLIFE_GAMES = 10.0
PREV_SEASON_WEIGHT = 0.35
OPP_SHRINK_MIN = 600.0  # pseudo-minutes of shrinkage for opponent positional factors
TEAMMATE_SHRINK_GAMES = 8.0


def to_day(s) -> np.ndarray:
    return pd.to_datetime(s).values.astype("datetime64[D]").astype(np.int64)


@dataclass
class LeagueParams:
    alpha: dict[str, float]
    pos_rate: dict[tuple[str, str], float]  # (pos group, stat) -> per-minute league rate
    blowout_starter: list[tuple[float, float]]  # (abs margin lower edge, minutes ratio)
    blowout_bench: list[tuple[float, float]]
    margin_sigma: float
    ot_rate: float
    b2b_ratio: float
    n_games: int


@dataclass
class GameContext:
    game_id: str
    team_id: str
    opp_team_id: str
    home: bool
    spread_for_team: float | None  # negative = team favored
    total: float | None
    known_out_teammates: list[str] = field(default_factory=list)
    b2b: bool = False


class History:
    """In-memory view of the database for fast as-of slicing."""

    def __init__(self):
        eng = get_engine()
        with eng.connect() as c:
            self.logs = pd.read_sql(select(PlayerGameLog), c)
            self.team_logs = pd.read_sql(select(TeamGameLog), c)
            self.games = pd.read_sql(select(Game), c)
            self.players = pd.read_sql(select(Player), c).set_index("athlete_id")
            self.teams = pd.read_sql(select(Team), c).set_index("team_id")
        L = self.logs
        for k, comps in STAT_COMPONENTS.items():
            if k not in L.columns:
                L[k] = L[comps].sum(axis=1)
        L["day"] = to_day(L["game_date"]) if len(L) else np.array([], dtype=np.int64)
        pos = self.players["position"].reindex(L["athlete_id"]).fillna("F").values
        L["pos_group"] = [POS_GROUP.get(p, "F") for p in pos]
        self.logs = L.sort_values(["athlete_id", "day"]).reset_index(drop=True)
        self.team_logs["day"] = to_day(self.team_logs["game_date"]) if len(self.team_logs) else []
        self.team_logs = self.team_logs.sort_values(["team_id", "day"]).reset_index(drop=True)
        g = self.games
        g["day"] = to_day(g["game_date"]) if len(g) else []
        self.games = g.set_index("game_id")
        self._by_player = {a: df for a, df in self.logs.groupby("athlete_id", sort=False)}
        self._by_team_players = {t: df for t, df in self.logs.groupby("team_id", sort=False)}
        self._team_logs = {t: df for t, df in self.team_logs.groupby("team_id", sort=False)}
        self._league_cache: dict[int, LeagueParams] = {}
        self._opp_cache: dict[tuple, dict] = {}

    # ---------- slicing ----------
    def player_before(self, athlete_id: str, day: int) -> pd.DataFrame:
        df = self._by_player.get(athlete_id)
        if df is None:
            return self.logs.iloc[0:0]
        return df[df["day"] < day]

    def team_games_before(self, team_id: str, day: int) -> pd.DataFrame:
        df = self._team_logs.get(team_id)
        if df is None:
            return self.team_logs.iloc[0:0]
        return df[df["day"] < day]

    # ---------- league-level parameters (re-estimated weekly, only from prior games) ----------
    def league(self, day: int) -> LeagueParams:
        key = day - (day % 7)
        if key in self._league_cache:
            return self._league_cache[key]
        L = self.logs[(self.logs["day"] < key) & (self.logs["day"] >= key - 400) & (~self.logs["dnp"]) & (self.logs["minutes"] > 0)]
        alpha, pos_rate = {}, {}
        sub = L[L["minutes"] >= 10].sort_values(["athlete_id", "day"])
        grp = sub.groupby(["athlete_id", "season"])
        prior_min = grp["minutes"].cumsum() - sub["minutes"]
        n_prior = grp.cumcount()
        for st in STAT_COMPONENTS:
            if len(sub) < 500:
                alpha[st] = {"pts": 0.06, "reb": 0.08, "ast": 0.12, "fg3m": 0.15}.get(st, 0.10)
            else:
                # Out-of-sample dispersion: each game is predicted from the same player's earlier games
                # only, so rate drift and role changes count as variance (an in-sample rate hides them).
                prior_sum = grp[st].cumsum() - sub[st]
                ok = (n_prior >= 5) & (prior_min > 0)
                mu = (prior_sum[ok] / prior_min[ok]) * sub["minutes"][ok]
                y = sub[st][ok]
                num = ((y - mu) ** 2 - mu).sum()
                alpha[st] = float(np.clip(num / (mu ** 2).sum(), 0.01, 1.5))
            for pg, sub2 in L.groupby("pos_group"):
                pos_rate[(pg, st)] = float(sub2[st].sum() / max(sub2["minutes"].sum(), 1))
        # Game script: minutes ratio vs the player's own season-average minutes, by final margin.
        G = self.games[(self.games["day"] < key) & (self.games["day"] >= key - 400) & self.games["home_score"].notna()]
        blow_s, blow_b, sigma, ot_rate = [(0, 1.0)], [(0, 1.0)], 12.5, 0.06
        b2b_ratio = 1.0
        if len(G) >= 100 and len(L) > 2000:
            margin = (G["home_score"] - G["away_score"]).abs()
            mg = margin.rename("absm")
            LL = L.join(mg, on="game_id")
            avg = LL.groupby(["athlete_id", "season"])["minutes"].transform("mean")
            LL = LL[avg >= 12]
            ratio = LL["minutes"] / avg[avg >= 12]
            edges = [0, 6, 11, 16, 21, 26]
            for starter, dest in ((True, blow_s), (False, blow_b)):
                dest.clear()
                sel = LL["starter"] == starter
                # Normalize by the group's overall ratio: starters' season averages include bench and
                # injury-shortened games, so raw ratios sit above 1 everywhere. Only the shape by
                # margin is wanted, with an expected multiplier of ~1 over the margin distribution.
                base = float(ratio[sel].mean()) if sel.sum() > 50 else 1.0
                for i, lo in enumerate(edges):
                    hi = edges[i + 1] if i + 1 < len(edges) else 99
                    m = sel & (LL["absm"] >= lo) & (LL["absm"] < hi)
                    dest.append((lo, float(ratio[m].mean()) / base if m.sum() > 50 else 1.0))
            gl = G.dropna(subset=["spread_home"])
            if len(gl) > 100:
                resid = (gl["home_score"] - gl["away_score"]) + gl["spread_home"]
                sigma = float(np.clip(resid.std(), 9, 16))
            ot_rate = float((G["periods"].fillna(4) > 4).mean())
            # Back-to-back minutes ratio for players averaging >= 24 minutes
            LL2 = L.sort_values(["athlete_id", "day"]).copy()
            LL2["prev_day"] = LL2.groupby("athlete_id")["day"].shift(1)
            LL2["avg"] = LL2.groupby(["athlete_id", "season"])["minutes"].transform("mean")
            core = LL2[LL2["avg"] >= 24]
            b2b = core[(core["day"] - core["prev_day"]) == 1]
            if len(b2b) > 200:
                b2b_ratio = float(np.clip((b2b["minutes"] / b2b["avg"]).mean() / (core["minutes"] / core["avg"]).mean(), 0.9, 1.02))
        lp = LeagueParams(alpha, pos_rate, blow_s, blow_b, sigma, ot_rate, b2b_ratio, int(len(G)))
        self._league_cache[key] = lp
        return lp

    # ---------- opponent positional factor ----------
    def opp_factor(self, opp_team_id: str, pos_group: str, stat: str, day: int, lp: LeagueParams) -> tuple[float, dict]:
        key = (opp_team_id, pos_group, day)
        if key not in self._opp_cache:
            L = self.logs
            sub = L[(L["opp_team_id"] == opp_team_id) & (L["day"] < day) & (L["day"] >= day - 120) &
                    (L["pos_group"] == pos_group) & (L["minutes"] > 0)]
            ng = sub["game_id"].nunique()
            sub = sub[sub["game_id"].isin(sub["game_id"].drop_duplicates().tail(20))]
            self._opp_cache[key] = {"mins": float(sub["minutes"].sum()), "sums": {s: float(sub[s].sum()) for s in STAT_COMPONENTS},
                                    "n_games": int(min(ng, 20))}
        c = self._opp_cache[key]
        league = lp.pos_rate.get((pos_group, stat))
        if not league or league <= 0:
            return 1.0, {"n_games": c["n_games"], "raw": None}
        raw = (c["sums"][stat] / c["mins"]) / league if c["mins"] > 0 else 1.0
        shrunk = (c["mins"] * raw + OPP_SHRINK_MIN) / (c["mins"] + OPP_SHRINK_MIN)
        return float(np.clip(shrunk, 0.85, 1.15)), {"n_games": c["n_games"], "raw": float(raw)}

    def team_pace(self, team_id: str, day: int) -> float | None:
        t = self.team_games_before(team_id, day).tail(15)
        if t.empty:
            return None
        return float((t["possessions"] * 4 / t["periods"].clip(lower=4)).mean())


@dataclass
class Projection:
    athlete_id: str
    market: str
    ok: bool
    reason: str | None
    mu_grid: np.ndarray | None = None  # (B, S) conditional NB means
    alpha: float = 0.1
    minutes_mean: float = 0.0
    minutes_sd: float = 0.0
    rate: float = 0.0
    opp_factor: float = 1.0
    teammate_factor: float = 1.0
    minutes_factor_teammates: float = 1.0
    emp_values: np.ndarray | None = None
    emp_weights: np.ndarray | None = None
    diagnostics: dict = field(default_factory=dict)

    def probs(self, line: float, rng_seed: int = 0) -> dict:
        """P(over), P(under), P(push) and the across-parameter-draw spread of P(over)."""
        n = 1.0 / max(self.alpha, 1e-4)
        mu = np.maximum(self.mu_grid, 1e-6)
        p = n / (n + mu)
        k = math.floor(line)
        sf = sps.nbinom.sf(k, n, p)  # P(X > floor(line)) = P(X >= floor(line)+1)
        is_int = float(line).is_integer()
        pmf = sps.nbinom.pmf(k, n, p) if is_int else np.zeros_like(mu)
        p_over_b = sf.mean(axis=1)
        p_push_b = pmf.mean(axis=1)
        p_under_b = 1 - p_over_b - p_push_b
        return {"p_over": float(p_over_b.mean()), "p_under": float(p_under_b.mean()), "p_push": float(p_push_b.mean()),
                "p_over_draws": p_over_b, "p_under_draws": p_under_b}

    def anchored_over(self, main_line: float, p_main_over: float, line: float) -> float | None:
        """Market-implied P(over `line`) for a one-sided alternate line: rescale the model's means so
        that P(over main_line) equals the main line's no-vig probability, then read off `line`.
        The scale is solved once per (main line, probability) and cached."""
        n = 1.0 / max(self.alpha, 1e-4)
        key = (main_line, round(p_main_over, 6))
        cache = self.__dict__.setdefault("_anchor_cache", {})
        if key not in cache:
            sub = self.mu_grid[::4, ::8]  # bisection on a subsample; final read uses the full grid
            k0 = math.floor(main_line)
            def p_over(c):
                mu = np.maximum(sub * c, 1e-6)
                return float(sps.nbinom.sf(k0, n, n / (n + mu)).mean())
            lo, hi = 0.5, 2.0
            if not (p_over(lo) <= p_main_over <= p_over(hi)):
                cache[key] = None
            else:
                for _ in range(25):
                    mid = (lo + hi) / 2
                    lo, hi = (mid, hi) if p_over(mid) < p_main_over else (lo, mid)
                cache[key] = (lo + hi) / 2
        c = cache[key]
        if c is None:
            return None
        mu = np.maximum(self.mu_grid * c, 1e-6)
        return float(sps.nbinom.sf(math.floor(line), n, n / (n + mu)).mean())

    def emp_probs(self, line: float) -> dict | None:
        if self.emp_values is None or len(self.emp_values) < 8:
            return None
        w = self.emp_weights / self.emp_weights.sum()
        v = self.emp_values
        po = float(w[v > line].sum())
        pp = float(w[v == line].sum()) if float(line).is_integer() else 0.0
        return {"p_over": po, "p_under": 1 - po - pp, "p_push": pp}

    def summary_dist(self, seed: int) -> dict:
        rng = np.random.default_rng(seed)
        n = 1.0 / max(self.alpha, 1e-4)
        mu = self.mu_grid.ravel()
        draws = rng.negative_binomial(n, n / (n + np.maximum(mu, 1e-6)))
        hist_max = int(np.percentile(draws, 99.5)) + 1
        counts = np.bincount(np.clip(draws, 0, hist_max), minlength=hist_max + 1)[: hist_max + 1]
        return {"mean": float(mu.mean()), "median": float(np.median(draws)), "p10": float(np.percentile(draws, 10)),
                "p90": float(np.percentile(draws, 90)), "pmf": (counts / counts.sum()).round(5).tolist()}


def _recency_weights(n: int, halflife: float) -> np.ndarray:
    age = np.arange(n)[::-1]
    return 0.5 ** (age / halflife)


def blowout_factor(curve: list[tuple[float, float]], abs_margin: np.ndarray) -> np.ndarray:
    edges = np.array([c[0] for c in curve])
    vals = np.array([c[1] for c in curve])
    idx = np.clip(np.searchsorted(edges, abs_margin, side="right") - 1, 0, len(vals) - 1)
    return vals[idx]


def project(h: History, athlete_id: str, market: str, day: int, season: int, ctx: GameContext,
            overrides: dict | None = None, B: int | None = None, S: int | None = None, seed: int | None = None) -> Projection:
    s = get_settings()
    B = B or s.param_draws
    S = S or s.script_draws
    seed = s.mc_seed if seed is None else seed
    ov = overrides or {}
    if market not in STAT_COMPONENTS:
        return Projection(athlete_id, market, False, "unsupported market for the count model")
    lp = h.league(day)
    hist = h.player_before(athlete_id, day)
    played = hist[(~hist["dnp"]) & (hist["minutes"] > 0)]
    cur = played[played["season"] == season]
    prev = played[played["season"] == season - 1]
    diag = {"n_current": int(len(cur)), "n_previous": int(len(prev))}
    if len(cur) < 3:
        return Projection(athlete_id, market, False, f"only {len(cur)} current-season games played", diagnostics=diag)

    # ----- minutes -----
    recent = cur.tail(15)
    wm = _recency_weights(len(recent), MIN_HALFLIFE_GAMES)
    m_hat = float(np.average(recent["minutes"], weights=wm))
    m_sd = float(math.sqrt(np.average((recent["minutes"] - m_hat) ** 2, weights=wm)))
    n_eff = float(wm.sum() ** 2 / (wm ** 2).sum())
    if len(prev) >= 10:
        m_hat = (n_eff * m_hat + 2.0 * float(prev["minutes"].mean())) / (n_eff + 2.0)
    m_sd = max(m_sd, 2.0)
    starter_share = float(cur.tail(5)["starter"].mean())
    diag.update(minutes_recent=round(m_hat, 2), minutes_sd=round(m_sd, 2), starter_share_l5=starter_share,
                minutes_l5=cur.tail(5)["minutes"].round(1).tolist())

    # ----- teammate absences (with/without splits, shrunk) -----
    rate_tm, min_tm, tm_detail = 1.0, 1.0, []
    team_hist = h._by_team_players.get(ctx.team_id)
    if ctx.known_out_teammates and team_hist is not None:
        th = team_hist[(team_hist["day"] < day) & (team_hist["season"] == season)]
        for tm in ctx.known_out_teammates:
            if tm == athlete_id:
                continue
            tmr = th[th["athlete_id"] == tm]
            if tmr.empty or tmr["minutes"].mean() < 24:
                continue
            played_games = set(tmr[(~tmr["dnp"]) & (tmr["minutes"] > 0)]["game_id"])
            without = cur[~cur["game_id"].isin(played_games)]
            with_ = cur[cur["game_id"].isin(played_games)]
            if len(without) < 2 or len(with_) < 3:
                tm_detail.append({"teammate": tm, "n_without": int(len(without)), "applied": False})
                continue
            def r(df):
                comps = STAT_COMPONENTS[market]
                return df[comps].sum(axis=1).sum() / max(df["minutes"].sum(), 1)
            ratio = r(without) / max(r(with_), 1e-6)
            mratio = without["minutes"].mean() / max(with_["minutes"].mean(), 1)
            k = len(without) / (len(without) + TEAMMATE_SHRINK_GAMES)
            rate_tm *= 1 + k * (ratio - 1)
            min_tm *= 1 + k * (mratio - 1)
            tm_detail.append({"teammate": tm, "n_without": int(len(without)), "rate_ratio_raw": round(float(ratio), 3),
                              "minutes_ratio_raw": round(float(mratio), 3), "shrink_weight": round(k, 3), "applied": True})
        rate_tm = float(np.clip(rate_tm, 0.85, 1.25))
        min_tm = float(np.clip(min_tm, 0.9, 1.15))
    diag["teammate_adjustments"] = tm_detail
    if ov.get("teammate_returns"):
        rate_tm, min_tm = 1.0, 1.0

    # ----- per-minute rate -----
    comps = STAT_COMPONENTS[market]
    pc = played.tail(82)
    y = pc[comps].sum(axis=1).to_numpy(float)
    mins = pc["minutes"].to_numpy(float)
    w = _recency_weights(len(pc), RATE_HALFLIFE_GAMES) * np.where(pc["season"].to_numpy() == season, 1.0, PREV_SEASON_WEIGHT)
    pg = POS_GROUP.get(str(h.players["position"].get(athlete_id, "F")), "F")
    prior = (prev[comps].sum(axis=1).sum() / prev["minutes"].sum()) if len(prev) >= 15 else lp.pos_rate.get((pg, market), 0.3)
    E = float((w * mins).sum() + RATE_PRIOR_MIN)
    rate = float(((w * y).sum() + RATE_PRIOR_MIN * prior) / E)
    # player-specific dispersion, shrunk toward the league value
    mu_hist = rate * mins
    a_player = float(((y - mu_hist) ** 2 - mu_hist).sum() / max((mu_hist ** 2).sum(), 1e-6))
    # In-sample residuals understate predictive variance, so the player value may only raise
    # dispersion above the out-of-sample league value, never lower it.
    a_player = max(a_player, lp.alpha[market])
    nw = len(pc) / (len(pc) + 20.0)
    alpha = float(np.clip(nw * a_player + (1 - nw) * lp.alpha[market], 0.005, 1.5))
    opp_f, opp_d = h.opp_factor(ctx.opp_team_id, pg, market, day, lp)
    diag.update(rate_per_min=round(rate, 4), prior_rate=round(float(prior), 4), alpha=round(alpha, 4),
                opp_factor=round(opp_f, 3), opp_detail=opp_d, position_group=pg)

    rate_mult = ov.get("rate_mult", 1.0)
    if ov.get("efficiency_regress") and "pts" in comps:
        # scoring efficiency regression: points component of the rate drops by 7%
        pts_share = float(pc["pts"].sum() / max(y.sum(), 1))
        rate_mult *= 1 - 0.07 * pts_share
    if ov.get("opp_defense_better"):
        opp_f = min(opp_f, 1.0) * 0.95
    pace_mult = ov.get("pace_mult", 1.0)

    # ----- simulation grid -----
    rng = np.random.default_rng(seed + (hash((athlete_id, market, day)) % 100000))
    rate_draws = rng.gamma(shape=rate * E / (1 + alpha * rate * 30), scale=(1 + alpha * rate * 30) / E, size=B)
    m_center = m_hat * min_tm * (lp.b2b_ratio if ctx.b2b else 1.0) * ov.get("minutes_mult", 1.0)
    m_draws_mean = rng.normal(m_center, m_sd / math.sqrt(max(n_eff, 1)), size=B)
    spread = ctx.spread_for_team if ctx.spread_for_team is not None else 0.0
    sigma = lp.margin_sigma if ctx.spread_for_team is not None else lp.margin_sigma * 1.15
    margin = rng.normal(-spread, sigma, size=(B, S))
    if ov.get("force_blowout"):
        margin = np.full((B, S), 25.0)
    curve = lp.blowout_starter if starter_share >= 0.5 else lp.blowout_bench
    gs = blowout_factor(curve, np.abs(margin))
    # overtime: concentrated in games that are close at the end; calibrated to the league OT rate
    close = np.abs(margin) < 3.0
    p_close = float(sps.norm.cdf(3, -spread, sigma) - sps.norm.cdf(-3, -spread, sigma))
    p_ot_given_close = min(0.9, lp.ot_rate / max(p_close, 0.05)) if not ov.get("no_overtime") else 0.0
    ot = close & (rng.random((B, S)) < p_ot_given_close)
    minutes = rng.normal(m_draws_mean[:, None] * gs, m_sd) + ot * 5.0 * min(1.0, m_hat / 34.0)
    minutes = np.clip(minutes, 0, 53)
    mu_grid = minutes * (rate_draws[:, None] * rate_mult * opp_f * rate_tm * pace_mult)

    # ----- second model: empirical, minutes-rescaled -----
    em = pc[pc["minutes"] >= 10]
    emp_vals = emp_w = None
    if len(em) >= 8:
        proj_m = m_center
        emp_vals = em[comps].sum(axis=1).to_numpy(float) * (proj_m / em["minutes"].to_numpy(float)) * opp_f * rate_tm
        emp_vals = np.round(emp_vals)  # outcomes are integers; compare like with like
        emp_w = _recency_weights(len(em), RATE_HALFLIFE_GAMES) * np.where(em["season"].to_numpy() == season, 1.0, PREV_SEASON_WEIGHT)

    diag.update(teammate_factor=round(rate_tm, 3), teammate_minutes_factor=round(min_tm, 3), p_overtime=round(float(ot.mean()), 4), p_blowout_20=round(float((np.abs(margin) >= 20).mean()), 4),
                expected_minutes_after_script=round(float(minutes.mean()), 2), minutes_cv=round(m_sd / max(m_hat, 1), 3),
                margin_sigma=round(sigma, 2), b2b_ratio=round(lp.b2b_ratio, 3) if ctx.b2b else None)
    return Projection(athlete_id, market, True, None, mu_grid, alpha, float(m_center), m_sd, rate, opp_f, rate_tm, min_tm,
                      emp_vals, emp_w, diag)


def project_double_double(h: History, athlete_id: str, day: int, season: int, ctx: GameContext) -> dict | None:
    """Empirical only: share of recency-weighted, minutes-rescaled past games with 2+ categories >= 10.
    A single model, so it is shown for research but never qualifies."""
    hist = h.player_before(athlete_id, day)
    played = hist[(~hist["dnp"]) & (hist["minutes"] >= 10)].tail(60)
    cur = played[played["season"] == season]
    if len(cur) < 5 or len(played) < 15:
        return None
    m = float(cur.tail(15)["minutes"].mean())
    scale = m / played["minutes"].to_numpy(float)
    cats = np.stack([np.round(played[c].to_numpy(float) * scale) for c in ("pts", "reb", "ast", "stl", "blk")])
    dd = ((cats >= 10).sum(axis=0) >= 2).astype(float)
    w = _recency_weights(len(played), RATE_HALFLIFE_GAMES) * np.where(played["season"].to_numpy() == season, 1.0, PREV_SEASON_WEIGHT)
    return {"p_yes": float(np.average(dd, weights=w)), "n": int(len(played))}
