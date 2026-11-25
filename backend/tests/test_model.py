"""Model properties on a synthetic fixture database (test-only data, never used by the app)."""
from datetime import date, timedelta

import numpy as np
import pytest

from app.db import Game, Player, PlayerGameLog, Team, TeamGameLog, session
from app.ingest import _insert_ignore
from app.models.engine import GameContext, History, project
from app.risk.engine import Gate, evaluate_quote, pick_top, player_flags

rng = np.random.default_rng(1)
START = date(2026, 10, 21)


@pytest.fixture(scope="module")
def hist():
    with session() as s:
        s.merge(Team(team_id="1", abbr="AAA", name="A"))
        s.merge(Team(team_id="2", abbr="BBB", name="B"))
        s.merge(Player(athlete_id="p1", name="Steady Starter", position="SG", team_id="1"))
        s.merge(Player(athlete_id="p2", name="Volatile Bench", position="C", team_id="1"))
        s.commit()
    games, plogs, tlogs = [], [], []
    for i in range(30):
        d = (START + timedelta(days=2 * i)).isoformat()
        gid = f"g{i}"
        games.append(Game(game_id=gid, season=2027, season_type=2, game_date=d, start_time=__import__("datetime").datetime(2026, 10, 21) + timedelta(days=2 * i),
                          home_team_id="1", away_team_id="2", status="STATUS_FINAL", home_score=110, away_score=105, periods=4,
                          spread_home=-3.0, total=220.0, box_loaded=True))
        m1 = float(np.clip(rng.normal(34, 2), 20, 44))
        pts = int(rng.poisson(0.7 * m1))
        plogs.append(dict(game_id=gid, athlete_id="p1", team_id="1", opp_team_id="2", game_date=d, season=2027, home=True, starter=True,
                          dnp=False, minutes=m1, pts=pts, reb=int(rng.poisson(5)), ast=int(rng.poisson(6)), fg3m=int(rng.poisson(2)),
                          fg3a=6, fgm=8, fga=17, ftm=3, fta=4, oreb=1, dreb=4, stl=1, blk=0, tov=2, pf=2, plus_minus=0))
        m2 = float(rng.choice([4, 12, 25, 30]))
        plogs.append(dict(game_id=gid, athlete_id="p2", team_id="1", opp_team_id="2", game_date=d, season=2027, home=True,
                          starter=bool(i % 2), dnp=False, minutes=m2, pts=int(rng.poisson(0.4 * m2)), reb=int(rng.poisson(0.3 * m2)),
                          ast=1, fg3m=0, fg3a=0, fgm=3, fga=6, ftm=1, fta=2, oreb=2, dreb=4, stl=0, blk=1, tov=1, pf=3, plus_minus=0))
        for t, o in (("1", "2"), ("2", "1")):
            tlogs.append(dict(game_id=gid, team_id=t, opp_team_id=o, game_date=d, season=2027, home=t == "1", pts=110, opp_pts=105,
                              fga=88, fta=22, oreb=10, tov=13, reb=44, ast=25, fg3m=12, fg3a=35, stl=7, blk=5, possessions=100.7, periods=4))
    with session() as s:
        for g in games:
            s.merge(g)
        s.commit()
    _insert_ignore(PlayerGameLog.__table__, plogs)
    _insert_ignore(TeamGameLog.__table__, tlogs)
    return History()


def ctx():
    return GameContext("x", "1", "2", True, -3.0, 220.0, [], False)


def day_after(h, n):
    return int(h.games["day"].min()) + 2 * n


def test_probabilities_sum_to_one(hist):
    pj = project(hist, "p1", "pts", day_after(hist, 30), 2027, ctx())
    assert pj.ok
    for line in (20.5, 24.0):
        pr = pj.probs(line)
        assert pr["p_over"] + pr["p_under"] + pr["p_push"] == pytest.approx(1.0, abs=1e-9)
    assert pj.probs(24.5)["p_push"] == 0


def test_reproducible_and_numerically_stable(hist):
    d = day_after(hist, 30)
    a = project(hist, "p1", "pts", d, 2027, ctx()).probs(23.5)["p_over"]
    b = project(hist, "p1", "pts", d, 2027, ctx()).probs(23.5)["p_over"]
    assert a == b  # fixed seed
    c = project(hist, "p1", "pts", d, 2027, ctx(), seed=999).probs(23.5)["p_over"]
    assert abs(a - c) < 0.02  # Monte Carlo error small relative to decision thresholds


def test_no_look_ahead(hist):
    """A projection as of game 20 must not change when later games exist in the database."""
    d = day_after(hist, 20)
    before = project(hist, "p1", "pts", d, 2027, ctx()).probs(23.5)["p_over"]
    h2 = History()
    h2.logs.loc[h2.logs["day"] >= d, "pts"] = 99  # corrupt the future
    h2._by_player = {a: df for a, df in h2.logs.groupby("athlete_id", sort=False)}
    after = project(h2, "p1", "pts", d, 2027, ctx()).probs(23.5)["p_over"]
    assert before == pytest.approx(after)


def test_minutes_down_reduces_over_probability(hist):
    d = day_after(hist, 30)
    base = project(hist, "p1", "pts", d, 2027, ctx()).probs(23.5)["p_over"]
    low = project(hist, "p1", "pts", d, 2027, ctx(), overrides={"minutes_mult": 0.8}).probs(23.5)["p_over"]
    assert low < base


def test_volatile_role_is_excluded(hist):
    pj = project(hist, "p2", "pts", day_after(hist, 30), 2027, ctx())
    codes = {f["code"] for f in player_flags(pj, None, "ladder_verified", "main")}
    assert "minutes_volatile" in codes


def test_injury_designation_excludes(hist):
    pj = project(hist, "p1", "pts", day_after(hist, 30), 2027, ctx())
    flags = player_flags(pj, "Day-To-Day", "ladder_verified", "main")
    assert any(f["code"] == "availability" and f["severity"] == "exclude" for f in flags)


def test_negative_ev_rejected_even_when_likely(hist):
    pj = project(hist, "p1", "pts", day_after(hist, 30), 2027, ctx())
    ev = evaluate_quote(pj, 10.5, "over", -2000, None, Gate(True, 1.0, 0.0, ""), [])
    assert ev["p_final"] > 0.9
    assert any(f["code"] in ("negative_ev", "negative_conservative_ev") for f in ev["flags"])


def test_conservative_below_point_estimate(hist):
    pj = project(hist, "p1", "pts", day_after(hist, 30), 2027, ctx())
    ev = evaluate_quote(pj, 22.5, "over", -110, -110, Gate(True, 1.0, 0.0, ""), [])
    assert ev["p_conservative"] <= ev["p_final"]


def test_pick_top_one_per_game_and_player():
    cands = [{"athlete_id": a, "game_id": g, "eval": {"ev_conservative": e}} for a, g, e in
             [("a", "g1", 0.1), ("a", "g1", 0.09), ("b", "g1", 0.08), ("c", "g2", 0.05), ("d", "g3", 0.01), ("e", "g4", 0.0)]]
    top = pick_top(cands, 3)
    assert [c["athlete_id"] for c in top] == ["a", "c", "d"]
