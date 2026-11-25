"""The Odds API adapter (authorized, keyed). Used when ODDS_API_KEY is set.

Docs: https://the-odds-api.com/liveapi/guides/v4/ . Player props are only served per event via
/v4/sports/basketball_nba/events/{id}/odds; each call costs (#markets x #regions) credits. The
adapter checks the x-requests-remaining header and stops before exceeding the configured budget.
Historical props (/v4/historical/...) need a paid plan and are not called by default.
"""
from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timezone

from ..config import get_settings
from ..http import RateLimitedClient

BASE = "https://api.the-odds-api.com/v4"
MARKET_MAP = {
    "player_points": "pts", "player_rebounds": "reb", "player_assists": "ast", "player_threes": "fg3m",
    "player_points_rebounds_assists": "pra", "player_points_rebounds": "pr", "player_points_assists": "pa",
    "player_rebounds_assists": "ra", "player_blocks": "blk", "player_steals": "stl",
    "player_turnovers": "tov", "player_blocks_steals": "stlblk", "player_double_double": "dd",
}
BOOK_NAMES = {"draftkings": "DraftKings", "fanduel": "FanDuel", "betmgm": "BetMGM", "williamhill_us": "Caesars"}

_client: RateLimitedClient | None = None
last_remaining: int | None = None


def enabled() -> bool:
    return bool(get_settings().odds_api_key)


def client() -> RateLimitedClient:
    global _client
    if _client is None:
        _client = RateLimitedClient("odds_api", 1.0)
    return _client


def norm_name(name: str) -> str:
    n = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    n = re.sub(r"\b(jr|sr|ii|iii|iv)\b\.?", "", n)
    return re.sub(r"[^a-z]", "", n)


def events() -> list[dict]:
    s = get_settings()
    status, data, headers = client().get_json(f"{BASE}/sports/basketball_nba/events", params={"apiKey": s.odds_api_key})
    _note_remaining(headers)
    if status != 200 or data is None:
        raise RuntimeError(f"The Odds API events failed (HTTP {status})")
    return data


def _note_remaining(headers):
    global last_remaining
    try:
        last_remaining = int(headers.get("x-requests-remaining"))
    except (TypeError, ValueError):
        pass


def parse_event_odds(data: dict, game_id: str, name_to_id: dict[str, str], retrieved_at: datetime, url: str) -> tuple[list[dict], list[str]]:
    """Returns (rows, unmatched player names). Outcomes carry explicit Over/Under labels."""
    rows, unmatched = [], set()
    for bm in data.get("bookmakers", []):
        book = BOOK_NAMES.get(bm["key"], bm.get("title", bm["key"]))
        for m in bm.get("markets", []):
            mkt = MARKET_MAP.get(m["key"].replace("_alternate", ""))
            if not mkt:
                continue
            kind = "alt" if m["key"].endswith("_alternate") else "main"
            upd = m.get("last_update")
            for o in m.get("outcomes", []):
                pname = o.get("description") or ""
                aid = name_to_id.get(norm_name(pname))
                if not aid:
                    unmatched.add(pname)
                    continue
                side = o["name"].lower()
                if mkt == "dd":
                    if side != "yes":
                        continue
                    line, kind_ = 0.5, "yes_no"
                else:
                    if side not in ("over", "under") or o.get("point") is None:
                        continue
                    line, kind_ = float(o["point"]), kind
                rows.append({"game_id": game_id, "athlete_id": aid, "athlete_name": pname, "retrieved_at": retrieved_at,
                             "source": "odds_api", "book": book, "market": mkt, "kind": kind_, "line": line, "side": side,
                             "american": int(o["price"]), "open_line": None, "open_american": None,
                             "side_verification": "labeled",
                             "quote_updated_at": datetime.fromisoformat(upd.replace("Z", "+00:00")).replace(tzinfo=None) if upd else None,
                             "is_historical_close": False, "source_url": url.split("?")[0]})
    return rows, sorted(unmatched)


def configured_markets() -> list[str]:
    return [m.strip() for m in get_settings().odds_api_markets.split(",") if m.strip()]


def event_odds(event_id: str, game_id: str, name_to_id: dict[str, str],
               markets: list[str] | None = None, tag: str | None = None) -> tuple[list[dict], list[str]]:
    s = get_settings()
    markets = markets or configured_markets()
    cost = len(markets) * len(s.odds_api_regions.split(","))
    if last_remaining is not None and last_remaining < cost:
        raise RuntimeError(f"The Odds API credit budget too low for this call ({last_remaining} left, needs {cost})")
    url = f"{BASE}/sports/basketball_nba/events/{event_id}/odds"
    status, data, headers = client().get_json(url, params={
        "apiKey": s.odds_api_key, "regions": s.odds_api_regions, "markets": ",".join(markets),
        "bookmakers": s.odds_api_bookmakers, "oddsFormat": "american"}, tag=tag)
    _note_remaining(headers)
    if status != 200 or data is None:
        raise RuntimeError(f"The Odds API event odds failed for {event_id} (HTTP {status})")
    return parse_event_odds(data, game_id, name_to_id, datetime.now(timezone.utc).replace(tzinfo=None), url)
