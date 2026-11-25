"""Data acquisition: schedule, box scores, historical props, today's props, injuries."""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from .config import get_settings
from .db import (FetchLog, Game, InjuryReport, Lineup, OddsSnapshot, Player, PlayerGameLog, Team, TeamGameLog,
                 get_engine, session, utcnow)
from .providers import espn, odds_api

log = logging.getLogger("ingest")

SEASON_WINDOWS = {  # ESPN season year -> (first, last) calendar dates to scan
    2026: (date(2025, 10, 1), date(2026, 4, 20)),
    2027: (date(2026, 10, 1), date(2027, 4, 20)),
}


def _insert_ignore(table, rows: list[dict]):
    if not rows:
        return
    eng = get_engine()
    ins = sqlite_insert if eng.dialect.name == "sqlite" else pg_insert
    with eng.begin() as conn:
        conn.execute(ins(table).on_conflict_do_nothing(), rows)


def possessions(fga: int, fta: int, oreb: int, tov: int) -> float:
    """Standard box-score possession estimate (Oliver): FGA + 0.44*FTA - OREB + TOV."""
    return fga + 0.44 * fta - oreb + tov


def upsert_games(events: list[dict]):
    with session() as s:
        for e in events:
            for t in (e["home_team"], e["away_team"]):
                s.merge(Team(team_id=t["id"], abbr=t["abbr"], name=t["name"]))
            g = s.get(Game, e["game_id"])
            if g is None:
                g = Game(game_id=e["game_id"])
                s.add(g)
            g.season, g.season_type, g.game_date = e["season"], e["season_type"], e["game_date"]
            g.start_time, g.home_team_id, g.away_team_id = e["start_time"], e["home_team"]["id"], e["away_team"]["id"]
            g.status, g.home_score, g.away_score = e["status"], e["home_score"], e["away_score"]
            if e.get("periods"):
                g.periods = e["periods"]
            if e.get("spread_home") is not None and not g.box_loaded:
                g.spread_home, g.total, g.lines_source = e["spread_home"], e["total"], e["lines_source"]
            g.updated_at = utcnow()
        s.commit()


def sync_schedule(season: int, through: date | None = None):
    first, last = SEASON_WINDOWS[season]
    if through:
        last = min(last, through)
    with session() as s:
        known = set(s.scalars(select(Game.game_date).where(Game.season == season, Game.status == "STATUS_FINAL")).all())
    d = first
    while d <= last:  # the scoreboard endpoint rejects date ranges, so scan day by day
        if d.isoformat() not in known or d >= last - timedelta(days=2):
            upsert_games([e for e in espn.scoreboard(d.strftime("%Y%m%d")) if e["season_type"] == 2])
        d += timedelta(days=1)


def load_boxscore(g: Game) -> bool:
    sm = espn.summary(g.game_id)
    if not sm or not sm["completed"] or not sm["players"]:
        return False
    opp = {g.home_team_id: g.away_team_id, g.away_team_id: g.home_team_id}
    prow, trow, lrow = [], [], []
    with session() as s:
        for p in sm["players"]:
            s.merge(Player(athlete_id=p["athlete_id"], name=p["name"], position=p["position"], team_id=p["team_id"], updated_at=utcnow()))
        s.commit()
    for p in sm["players"]:
        prow.append({k: p[k] for k in ("athlete_id", "team_id", "starter", "dnp", "dnp_reason", "minutes", "pts", "reb", "ast",
                                       "fg3m", "fg3a", "fgm", "fga", "ftm", "fta", "oreb", "dreb", "stl", "blk", "tov", "pf",
                                       "plus_minus")} | {"game_id": g.game_id, "opp_team_id": opp.get(p["team_id"], ""),
                                                         "game_date": g.game_date, "season": g.season,
                                                         "home": p["team_id"] == g.home_team_id})
        if p["starter"]:
            lrow.append({"game_id": g.game_id, "team_id": p["team_id"], "athlete_id": p["athlete_id"], "kind": "observed_starter",
                         "retrieved_at": utcnow()})
    for t in sm["teams"]:
        o = opp.get(t["team_id"], "")
        trow.append({**t, "game_id": g.game_id, "opp_team_id": o, "game_date": g.game_date, "season": g.season,
                     "pts": sm["scores"].get(t["team_id"], 0), "opp_pts": sm["scores"].get(o, 0),
                     "possessions": possessions(t["fga"], t["fta"], t["oreb"], t["tov"]), "periods": sm["periods"] or 4})
    _insert_ignore(PlayerGameLog.__table__, prow)
    _insert_ignore(TeamGameLog.__table__, trow)
    _insert_ignore(Lineup.__table__, lrow)
    with session() as s:
        gg = s.get(Game, g.game_id)
        gg.box_loaded = True
        gg.periods = sm["periods"] or gg.periods
        if gg.spread_home is None and sm["spread_home"] is not None:
            gg.spread_home, gg.total, gg.lines_source = sm["spread_home"], sm["total"], sm["lines_source"]
        s.commit()
    return True


def store_odds(rows: list[dict]):
    names = {}
    with session() as s:
        ids = {r["athlete_id"] for r in rows}
        if ids:
            names = dict(s.execute(select(Player.athlete_id, Player.name).where(Player.athlete_id.in_(ids))).all())
    for r in rows:
        r.setdefault("athlete_name", names.get(r["athlete_id"]))
        if r.get("athlete_name") is None:
            r["athlete_name"] = names.get(r["athlete_id"])
    _insert_ignore(OddsSnapshot.__table__, rows)


def load_historical_props(g: Game) -> int:
    res = espn.propbets(g.game_id, historical=True)
    with session() as s:
        s.execute(update(Game).where(Game.game_id == g.game_id).values(props_loaded=True))
        s.commit()
    if not res:
        return 0
    rows, _ = res
    store_odds(rows)
    return len(rows)


def backfill(seasons: list[int] | None = None, props: bool = True, progress=print):
    today = datetime.now(timezone.utc).date()
    seasons = seasons or get_settings().season_list
    for season in seasons:
        progress(f"schedule {season}")
        sync_schedule(season, through=today)
    with session() as s:
        todo = s.scalars(select(Game).where(Game.box_loaded.is_(False), Game.status == "STATUS_FINAL")
                         .order_by(Game.start_time)).all()
    progress(f"box scores to load: {len(todo)}")
    for i, g in enumerate(todo):
        try:
            load_boxscore(g)
        except Exception as ex:  # one malformed box score must not stop the backfill
            log.warning("box score %s failed: %r", g.game_id, ex)
            progress(f"  box {g.game_id} failed: {ex!r}")
        if i % 50 == 0:
            progress(f"  box {i}/{len(todo)} {g.game_date}")
    if props:
        cur = max(seasons)
        with session() as s:
            todo = s.scalars(select(Game).where(Game.props_loaded.is_(False), Game.status == "STATUS_FINAL",
                                                Game.season == cur).order_by(Game.start_time)).all()
        progress(f"historical prop boards to load: {len(todo)}")
        for i, g in enumerate(todo):
            try:
                n = load_historical_props(g)
            except Exception as ex:
                progress(f"  props {g.game_id} failed: {ex!r}")
                continue
            if i % 25 == 0:
                progress(f"  props {i}/{len(todo)} {g.game_date} rows={n}")


def refresh_injuries() -> int:
    rows, at, url = espn.injuries()
    with session() as s:
        for r in rows:
            s.add(InjuryReport(retrieved_at=at, source="espn", source_url=url, **r))
        s.commit()
    return len(rows)


def refresh_slate(slate: str) -> dict:
    """Pull today's schedule, current prop boards for not-yet-started games, injuries."""
    report = {"slate_date": slate, "errors": [], "props_rows": 0, "games": 0, "odds_api": None}
    ymd = slate.replace("-", "")
    events = [e for e in espn.scoreboard(ymd) if e["game_date"] == slate]
    upsert_games(events)
    report["games"] = len(events)
    now = utcnow()
    for e in events:
        if e["state"] != "pre" or e["start_time"] <= now:
            continue
        res = espn.propbets(e["game_id"])
        if res is None:
            report["errors"].append(f"no DraftKings prop board for {e['away_team']['abbr']}@{e['home_team']['abbr']}")
            continue
        rows, _ = res
        store_odds(rows)
        report["props_rows"] += len(rows)
    if odds_api.enabled():
        report["odds_api"] = refresh_odds_api(events) if _odds_api_due(report, events) else report.get("odds_api")
    try:
        report["injuries"] = refresh_injuries()
    except RuntimeError as ex:
        report["errors"].append(str(ex))
    # Make sure yesterday's box scores are in (needed for features and for settling predictions).
    with session() as s:
        todo = s.scalars(select(Game).where(Game.box_loaded.is_(False), Game.status == "STATUS_FINAL")).all()
    for g in todo:
        try:
            load_boxscore(g)
        except Exception as ex:
            report["errors"].append(f"box score {g.game_id}: {ex!r}")
    return report


def _odds_api_due(report: dict, events: list[dict] | None = None) -> bool:
    """Credits are scarce (free tier 500/month), so Odds API pulls run on their own schedule:
    at most ODDS_API_PULLS_PER_DAY per slate, at least ODDS_API_REFRESH_MIN apart, and only once
    the next tip-off is within ODDS_API_LEAD_HOURS (lines are most complete then)."""
    s = get_settings()
    now = utcnow()
    with session() as ss:
        pulls = ss.scalars(select(FetchLog.at).where(FetchLog.source == "odds_api", FetchLog.ok.is_(True),
                                                     FetchLog.url.like("%/events/%/odds%"),
                                                     FetchLog.note.is_distinct_from("verification"))).all()
    tz = ZoneInfo(s.timezone)
    today = datetime.now(tz).date()
    pull_days = {}
    for at in pulls:  # several event calls make up one pull; group them into pulls by 10-minute gaps
        pull_days.setdefault(at.replace(tzinfo=timezone.utc).astimezone(tz).date(), []).append(at)
    todays = sorted(pull_days.get(today, []))
    n_today = sum(1 for i, at in enumerate(todays) if i == 0 or (at - todays[i - 1]) > timedelta(minutes=10))
    if n_today >= s.odds_api_pulls_per_day:
        report["odds_api"] = {"skipped": f"daily pull limit reached ({n_today}/{s.odds_api_pulls_per_day}) to stay inside the free credit quota"}
        return False
    last = max(pulls) if pulls else None
    if last is not None and now - last < timedelta(minutes=s.odds_api_refresh_min):
        wait = s.odds_api_refresh_min - int((now - last).total_seconds() // 60)
        report["odds_api"] = {"skipped": f"last pull {last:%H:%M} UTC; next allowed in {wait} min (ODDS_API_REFRESH_MIN)"}
        return False
    if events is not None:
        starts = [e["start_time"] for e in events if e.get("state") == "pre" and e["start_time"] > now]
        if not starts:
            report["odds_api"] = {"skipped": "no pregame games left"}
            return False
        lead = (min(starts) - now).total_seconds() / 3600
        if lead > s.odds_api_lead_hours:
            report["odds_api"] = {"skipped": f"scheduled: pulls once the next tip-off is within {s.odds_api_lead_hours:g} h "
                                             f"(now {lead:.1f} h away)"}
            return False
    return True


def daily_allowance(remaining: int, today: date | None = None) -> int:
    """Credits this slate may spend: what is left above the reserve, spread over the days left in the
    calendar month (the free quota resets monthly)."""
    s = get_settings()
    today = today or datetime.now(ZoneInfo(s.timezone)).date()
    nxt = (today.replace(day=28) + timedelta(days=4)).replace(day=1)
    days_left = (nxt - today).days
    return max(0, (remaining - s.odds_api_reserve_credits) // max(days_left, 1))


def plan_pull(n_games: int, allowance: int, markets: list[str]) -> tuple[list[str], int]:
    """Choose (markets, number of games) so that markets x games <= allowance, keeping all games
    when possible and dropping the lowest-priority markets first."""
    if n_games <= 0 or allowance <= 0:
        return [], 0
    per_game = min(len(markets), allowance // n_games)
    if per_game >= 1:
        return markets[:per_game], n_games
    return markets[:1], min(n_games, allowance)


def refresh_odds_api(events: list[dict], max_games: int | None = None, tag: str | None = None) -> dict:
    s = get_settings()
    out = {"rows": 0, "unmatched": [], "errors": [], "games_pulled": 0, "games_skipped_budget": 0}
    with session() as ss:
        name_to_id = {odds_api.norm_name(n): a for a, n in ss.execute(select(Player.athlete_id, Player.name)).all()}
    try:
        oa_events = odds_api.events()  # free call; also reports remaining credits
    except RuntimeError as ex:
        out["errors"].append(str(ex))
        return out
    remaining = odds_api.last_remaining if odds_api.last_remaining is not None else 0
    regions = len(s.odds_api_regions.split(","))
    by_teams = {(e["home_team"]["name"], e["away_team"]["name"]): e for e in events}
    todo = []
    for oe in sorted(oa_events, key=lambda x: x.get("commence_time", "")):  # earliest tip-offs first
        e = by_teams.get((oe["home_team"], oe["away_team"]))
        if e and e["state"] == "pre":
            todo.append((oe, e))
    if max_games is not None:
        todo = todo[:max_games]
    allowance = daily_allowance(remaining) // regions
    markets, n = plan_pull(len(todo), allowance, odds_api.configured_markets())
    out.update(credits_before=remaining, allowance=allowance * regions, markets=markets, games_planned=n)
    out["games_skipped_budget"] = len(todo) - n
    for oe, e in todo[:n]:
        try:
            rows, unmatched = odds_api.event_odds(oe["id"], e["game_id"], name_to_id, markets, tag=tag)
        except RuntimeError as ex:
            out["errors"].append(str(ex))
            break
        store_odds(rows)
        out["rows"] += len(rows)
        out["games_pulled"] += 1
        out["unmatched"] += unmatched
    out["credits_remaining"] = odds_api.last_remaining
    return out


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)
    if len(sys.argv) > 1 and sys.argv[1] == "backfill":
        backfill()
