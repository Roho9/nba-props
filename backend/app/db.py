"""SQLAlchemy schema. SQLite locally; every type used here also maps cleanly onto PostgreSQL."""
from __future__ import annotations

from datetime import datetime, timezone
from functools import lru_cache

from sqlalchemy import (JSON, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text,
                        UniqueConstraint, create_engine, event)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from .config import get_settings


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class Team(Base):
    __tablename__ = "teams"
    team_id: Mapped[str] = mapped_column(String, primary_key=True)  # ESPN team id
    abbr: Mapped[str] = mapped_column(String)
    name: Mapped[str] = mapped_column(String)


class Player(Base):
    __tablename__ = "players"
    athlete_id: Mapped[str] = mapped_column(String, primary_key=True)  # ESPN athlete id
    name: Mapped[str] = mapped_column(String, index=True)
    position: Mapped[str | None] = mapped_column(String, nullable=True)
    team_id: Mapped[str | None] = mapped_column(String, nullable=True)  # latest observed team
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Game(Base):
    __tablename__ = "games"
    game_id: Mapped[str] = mapped_column(String, primary_key=True)
    season: Mapped[int] = mapped_column(Integer, index=True)
    season_type: Mapped[int] = mapped_column(Integer)
    game_date: Mapped[str] = mapped_column(String, index=True)  # local slate date YYYY-MM-DD (ET)
    start_time: Mapped[datetime] = mapped_column(DateTime)
    home_team_id: Mapped[str] = mapped_column(String)
    away_team_id: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String)
    home_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    away_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    periods: Mapped[int | None] = mapped_column(Integer, nullable=True)
    spread_home: Mapped[float | None] = mapped_column(Float, nullable=True)  # negative = home favored
    total: Mapped[float | None] = mapped_column(Float, nullable=True)
    lines_source: Mapped[str | None] = mapped_column(String, nullable=True)
    box_loaded: Mapped[bool] = mapped_column(Boolean, default=False)
    props_loaded: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class PlayerGameLog(Base):
    __tablename__ = "player_game_logs"
    __table_args__ = (UniqueConstraint("game_id", "athlete_id"), Index("ix_pgl_ath_date", "athlete_id", "game_date"))
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    game_id: Mapped[str] = mapped_column(String, ForeignKey("games.game_id"))
    athlete_id: Mapped[str] = mapped_column(String)
    team_id: Mapped[str] = mapped_column(String)
    opp_team_id: Mapped[str] = mapped_column(String)
    game_date: Mapped[str] = mapped_column(String)
    season: Mapped[int] = mapped_column(Integer)
    home: Mapped[bool] = mapped_column(Boolean)
    starter: Mapped[bool] = mapped_column(Boolean)
    dnp: Mapped[bool] = mapped_column(Boolean)
    dnp_reason: Mapped[str | None] = mapped_column(String, nullable=True)
    minutes: Mapped[float] = mapped_column(Float, default=0)
    pts: Mapped[int] = mapped_column(Integer, default=0)
    reb: Mapped[int] = mapped_column(Integer, default=0)
    ast: Mapped[int] = mapped_column(Integer, default=0)
    fg3m: Mapped[int] = mapped_column(Integer, default=0)
    fg3a: Mapped[int] = mapped_column(Integer, default=0)
    fgm: Mapped[int] = mapped_column(Integer, default=0)
    fga: Mapped[int] = mapped_column(Integer, default=0)
    ftm: Mapped[int] = mapped_column(Integer, default=0)
    fta: Mapped[int] = mapped_column(Integer, default=0)
    oreb: Mapped[int] = mapped_column(Integer, default=0)
    dreb: Mapped[int] = mapped_column(Integer, default=0)
    stl: Mapped[int] = mapped_column(Integer, default=0)
    blk: Mapped[int] = mapped_column(Integer, default=0)
    tov: Mapped[int] = mapped_column(Integer, default=0)
    pf: Mapped[int] = mapped_column(Integer, default=0)
    plus_minus: Mapped[int] = mapped_column(Integer, default=0)


class TeamGameLog(Base):
    __tablename__ = "team_game_logs"
    __table_args__ = (UniqueConstraint("game_id", "team_id"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    game_id: Mapped[str] = mapped_column(String, ForeignKey("games.game_id"))
    team_id: Mapped[str] = mapped_column(String, index=True)
    opp_team_id: Mapped[str] = mapped_column(String)
    game_date: Mapped[str] = mapped_column(String, index=True)
    season: Mapped[int] = mapped_column(Integer)
    home: Mapped[bool] = mapped_column(Boolean)
    pts: Mapped[int] = mapped_column(Integer)
    opp_pts: Mapped[int] = mapped_column(Integer)
    fga: Mapped[int] = mapped_column(Integer)
    fta: Mapped[int] = mapped_column(Integer)
    oreb: Mapped[int] = mapped_column(Integer)
    tov: Mapped[int] = mapped_column(Integer)
    reb: Mapped[int] = mapped_column(Integer)
    ast: Mapped[int] = mapped_column(Integer)
    fg3m: Mapped[int] = mapped_column(Integer)
    fg3a: Mapped[int] = mapped_column(Integer)
    stl: Mapped[int] = mapped_column(Integer)
    blk: Mapped[int] = mapped_column(Integer)
    possessions: Mapped[float] = mapped_column(Float)
    periods: Mapped[int] = mapped_column(Integer)


class InjuryReport(Base):
    __tablename__ = "injury_reports"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    source: Mapped[str] = mapped_column(String)
    team_id: Mapped[str | None] = mapped_column(String, nullable=True)
    athlete_id: Mapped[str] = mapped_column(String, index=True)
    athlete_name: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String)
    reported_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_url: Mapped[str] = mapped_column(String)


class Lineup(Base):
    """Observed starters (from box scores) or confirmed pregame lineups when a source provides them."""
    __tablename__ = "lineups"
    __table_args__ = (UniqueConstraint("game_id", "team_id", "athlete_id", "kind"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    game_id: Mapped[str] = mapped_column(String, index=True)
    team_id: Mapped[str] = mapped_column(String)
    athlete_id: Mapped[str] = mapped_column(String)
    kind: Mapped[str] = mapped_column(String)  # observed_starter | confirmed_pregame
    retrieved_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class OddsSnapshot(Base):
    """One quote for one side of one prop, as retrieved. Rows are append-only."""
    __tablename__ = "odds_snapshots"
    __table_args__ = (
        UniqueConstraint("game_id", "athlete_id", "market", "kind", "line", "side", "book", "quote_updated_at", "source"),
        Index("ix_odds_game_mkt", "game_id", "athlete_id", "market"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    source: Mapped[str] = mapped_column(String)  # espn_dk | odds_api
    book: Mapped[str] = mapped_column(String)
    game_id: Mapped[str] = mapped_column(String)
    athlete_id: Mapped[str] = mapped_column(String)
    athlete_name: Mapped[str | None] = mapped_column(String, nullable=True)
    market: Mapped[str] = mapped_column(String)  # pts, reb, ast, pra, pr, pa, ra, fg3m, stl, blk, stlblk, tov, dd
    kind: Mapped[str] = mapped_column(String)  # main | alt | yes_no
    line: Mapped[float] = mapped_column(Float)  # over means stat > line (alt "X+" stored as X-0.5)
    side: Mapped[str] = mapped_column(String)  # over | under | yes
    american: Mapped[int] = mapped_column(Integer)
    open_line: Mapped[float | None] = mapped_column(Float, nullable=True)
    open_american: Mapped[int | None] = mapped_column(Integer, nullable=True)
    side_verification: Mapped[str] = mapped_column(String, default="n/a")  # ladder_verified | order_only | contradicted | labeled
    quote_updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    is_historical_close: Mapped[bool] = mapped_column(Boolean, default=False)
    source_url: Mapped[str] = mapped_column(String)


class ModelVersion(Base):
    __tablename__ = "model_versions"
    version: Mapped[str] = mapped_column(String, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    description: Mapped[str] = mapped_column(Text)
    params: Mapped[dict] = mapped_column(JSON)


class ModelRun(Base):
    __tablename__ = "model_runs"
    run_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    slate_date: Mapped[str] = mapped_column(String, index=True)
    model_version: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String)  # running | ok | failed
    summary: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class Prediction(Base):
    """Immutable published research candidate. Never updated after first insert, except the
    outcome columns and the invalidation flag, which are separate facts about the same record."""
    __tablename__ = "predictions"
    __table_args__ = (UniqueConstraint("slate_date", "game_id", "athlete_id", "market", "line", "side", "book", "model_version"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    run_id: Mapped[int] = mapped_column(Integer)
    slate_date: Mapped[str] = mapped_column(String, index=True)
    game_id: Mapped[str] = mapped_column(String)
    game_start: Mapped[datetime] = mapped_column(DateTime)
    athlete_id: Mapped[str] = mapped_column(String)
    athlete_name: Mapped[str] = mapped_column(String)
    team_abbr: Mapped[str] = mapped_column(String)
    opp_abbr: Mapped[str] = mapped_column(String)
    market: Mapped[str] = mapped_column(String)
    line: Mapped[float] = mapped_column(Float)
    side: Mapped[str] = mapped_column(String)
    book: Mapped[str] = mapped_column(String)
    american: Mapped[int] = mapped_column(Integer)
    p_model: Mapped[float] = mapped_column(Float)
    p_conservative: Mapped[float] = mapped_column(Float)
    p_market_novig: Mapped[float | None] = mapped_column(Float, nullable=True)
    ev_per_unit: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String)  # qualified | research_only
    model_version: Mapped[str] = mapped_column(String)
    snapshot: Mapped[dict] = mapped_column(JSON)  # full analysis payload as published
    invalidated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    invalidation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    closing_line: Mapped[float | None] = mapped_column(Float, nullable=True)
    closing_american: Mapped[int | None] = mapped_column(Integer, nullable=True)
    actual_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    result: Mapped[str | None] = mapped_column(String, nullable=True)  # win | loss | push | void
    settled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class BacktestRun(Base):
    __tablename__ = "backtest_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    model_version: Mapped[str] = mapped_column(String)
    report: Mapped[dict] = mapped_column(JSON)


class FetchLog(Base):
    """Data source metadata: every outbound request, its status and timing."""
    __tablename__ = "fetch_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    source: Mapped[str] = mapped_column(String, index=True)
    url: Mapped[str] = mapped_column(Text)
    status: Mapped[int] = mapped_column(Integer)
    ok: Mapped[bool] = mapped_column(Boolean)
    elapsed_ms: Mapped[int] = mapped_column(Integer)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)


@lru_cache
def get_engine():
    url = get_settings().database_url
    eng = create_engine(url, connect_args={"check_same_thread": False, "timeout": 30} if url.startswith("sqlite") else {})
    if url.startswith("sqlite"):
        @event.listens_for(eng, "connect")
        def _pragma(conn, _):
            cur = conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA synchronous=NORMAL")
            cur.close()
    Base.metadata.create_all(eng)
    return eng


def session():
    return sessionmaker(bind=get_engine(), expire_on_commit=False)()
