"""Environment-based configuration. All secrets come from backend/.env, never the frontend."""
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BACKEND_DIR / ".env", extra="ignore")

    timezone: str = "America/New_York"
    database_url: str = f"sqlite:///{BACKEND_DIR / 'data' / 'nba_props.sqlite3'}"

    # ESPN's public JSON endpoints are undocumented. They are not an officially licensed API,
    # so this is an explicit opt-in. See docs/DATA_SOURCES.md.
    espn_enabled: bool = True
    espn_min_interval_s: float = 0.35  # >= ~3 requests/second, single connection

    # The Odds API (authorized, keyed). Free tier = 500 credits/month; each event-odds call
    # costs (markets x regions) credits.
    odds_api_key: str = ""
    odds_api_regions: str = "us"
    # DraftKings already comes from ESPN; requesting it twice would mix two snapshots of one book.
    odds_api_bookmakers: str = "fanduel,betmgm,williamhill_us"
    # Priority order: when the daily credit allowance cannot cover every market for every game,
    # the allocator keeps the first N.
    odds_api_markets: str = (
        "player_points,player_rebounds,player_assists,player_points_rebounds_assists,player_threes,"
        "player_points_rebounds,player_points_assists,player_rebounds_assists,player_blocks,"
        "player_steals,player_turnovers,player_blocks_steals"
    )
    odds_api_monthly_credit_budget: int = 500
    odds_api_pulls_per_day: int = 1  # free tier: one pre-tip snapshot per slate
    odds_api_lead_hours: float = 3.0  # pull once the next tip-off is within this many hours
    odds_api_refresh_min: int = 360  # minimum minutes between pulls when pulls_per_day > 1
    odds_api_reserve_credits: int = 25  # never spend below this many remaining credits

    # Optional LLM explanation layer (off unless a key is present).
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-5-5"

    # Data freshness and refresh
    odds_stale_after_min: int = 45
    injuries_stale_after_min: int = 120
    auto_refresh_min: int = 30

    # Seasons ingested (ESPN season year = year the season ends)
    seasons: str = "2026,2027"

    # Model
    mc_seed: int = 20261125
    param_draws: int = 200
    script_draws: int = 400

    # Risk defaults (overridden by the validation report when it supplies tuned values)
    min_games_current_season: int = 8
    max_minutes_cv: float = 0.25
    max_prob_sd: float = 0.07
    max_model_disagreement: float = 0.10
    min_conservative_edge: float = 0.0
    paper_stake_units: float = 1.0

    @property
    def season_list(self) -> list[int]:
        return [int(s) for s in self.seasons.split(",") if s.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
