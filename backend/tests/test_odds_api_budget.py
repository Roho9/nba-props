from datetime import date, timedelta

from app.db import FetchLog, session, utcnow
from app.ingest import _odds_api_due, daily_allowance, plan_pull

MKTS = ["player_points", "player_rebounds", "player_assists", "player_points_rebounds_assists", "player_threes"]


def test_pull_waits_for_lead_window_then_limits_to_one_per_day():
    far = [{"state": "pre", "start_time": utcnow() + timedelta(hours=10)}]
    near = [{"state": "pre", "start_time": utcnow() + timedelta(hours=2)}]
    report = {}
    assert not _odds_api_due(report, far)
    assert "within 3 h" in report["odds_api"]["skipped"]
    assert _odds_api_due({}, near)
    with session() as s:
        s.add(FetchLog(source="odds_api", url="https://api.the-odds-api.com/v4/sports/basketball_nba/events/abc/odds",
                       status=200, ok=True, elapsed_ms=10, at=utcnow()))
        s.commit()
    report = {}
    assert not _odds_api_due(report, near)
    assert "daily pull limit" in report["odds_api"]["skipped"]


def test_daily_allowance_spreads_remaining_credits_over_the_month():
    # 499 left, 25 reserved, 6 days left in November (25th..30th)
    assert daily_allowance(499, date(2026, 11, 25)) == (499 - 25) // 6
    assert daily_allowance(20, date(2026, 11, 25)) == 0


def test_plan_pull_drops_low_priority_markets_before_games():
    assert plan_pull(9, 79, MKTS) == (MKTS, 9)              # 5 markets x 9 games = 45 <= 79
    assert plan_pull(9, 30, MKTS) == (MKTS[:3], 9)          # 3 x 9 = 27
    assert plan_pull(9, 5, MKTS) == (MKTS[:1], 5)           # cannot cover every game: earliest 5
    assert plan_pull(9, 0, MKTS) == ([], 0)
