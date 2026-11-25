"""ESPN public JSON adapter (schedule, box scores, injuries, DraftKings props as displayed by ESPN).

These endpoints are undocumented and unsupported. They need no key, but ESPN does not publish
terms that grant API use, so the adapter is gated behind ESPN_ENABLED, keeps a low request rate,
and is intended for personal, non-commercial research only. See docs/DATA_SOURCES.md.
"""
from __future__ import annotations

import math
import re
from collections import defaultdict
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from ..config import get_settings
from ..http import RateLimitedClient

SITE = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba"
CORE = "https://sports.core.api.espn.com/v2/sports/basketball/leagues/nba"
DK_PROVIDER_ID = "100"  # ESPN provider id for DraftKings
ET = ZoneInfo("America/New_York")

MAIN_MARKETS = {
    "Total Points": "pts", "Total Rebounds": "reb", "Total Assists": "ast",
    "Total Points, Rebounds, and Assists": "pra", "Total Points and Rebounds": "pr",
    "Total Points and Assists": "pa", "Total Assists and Rebounds": "ra",
    "Total 3-Point Field Goals": "fg3m", "Total Steals": "stl", "Total Blocks": "blk",
    "Total Turnovers": "tov", "Total Steals and Blocks": "stlblk",
}
ALT_MARKETS = {
    "Points Milestones": "pts", "Rebounds Milestones": "reb", "Assists Milestones": "ast",
    "Points + Assists + Rebounds Milestones": "pra", "Points + Rebounds Milestones": "pr",
    "Points + Assists Milestones": "pa", "Rebounds + Assists Milestones": "ra",
    "3-Point Field Goals Milestones": "fg3m", "Steals Milestones": "stl", "Blocks Milestones": "blk",
}
YES_MARKETS = {"To Record a Double Double": "dd"}

_client: RateLimitedClient | None = None


def client() -> RateLimitedClient:
    global _client
    if _client is None:
        _client = RateLimitedClient("espn", get_settings().espn_min_interval_s)
    return _client


def _parse_dt(s: str) -> datetime:
    s = s.replace("Z", "+00:00")
    if re.match(r".*T\d\d:\d\d\+", s):
        s = s.replace("+", ":00+", 1)
    return datetime.fromisoformat(s).astimezone(timezone.utc).replace(tzinfo=None)


def slate_date_of(start_utc: datetime) -> str:
    """NBA slates are dated in US Eastern time."""
    return start_utc.replace(tzinfo=timezone.utc).astimezone(ET).date().isoformat()


def parse_spread(details: str | None, home_abbr: str, away_abbr: str) -> float | None:
    """'PHI -1.5' -> spread from the home team's perspective (negative = home favored)."""
    if not details:
        return None
    if details.strip().upper() in ("EVEN", "PK", "PICK"):
        return 0.0
    m = re.match(r"^\s*([A-Z]{2,4})\s+([+-]?\d+(?:\.\d+)?)\s*$", details)
    if not m:
        return None
    abbr, val = m.group(1), float(m.group(2))
    if abbr == home_abbr:
        return val
    if abbr == away_abbr:
        return -val
    return None


def parse_event(e: dict) -> dict:
    c = e["competitions"][0]
    teams = {t["homeAway"]: t for t in c["competitors"]}
    home, away = teams["home"], teams["away"]
    start = _parse_dt(e["date"])
    odds = (c.get("odds") or [{}])[0]
    st = c["status"]["type"]
    return {
        "game_id": e["id"],
        "season": e["season"]["year"],
        "season_type": e["season"]["type"],
        "start_time": start,
        "game_date": slate_date_of(start),
        "home_team": {"id": home["team"]["id"], "abbr": home["team"]["abbreviation"], "name": home["team"]["displayName"]},
        "away_team": {"id": away["team"]["id"], "abbr": away["team"]["abbreviation"], "name": away["team"]["displayName"]},
        "status": st["name"],
        "state": st.get("state"),
        "completed": bool(st.get("completed")),
        "home_score": int(home["score"]) if home.get("score") not in (None, "") else None,
        "away_score": int(away["score"]) if away.get("score") not in (None, "") else None,
        "periods": c["status"].get("period") or None,
        "spread_home": parse_spread(odds.get("details"), home["team"]["abbreviation"], away["team"]["abbreviation"]),
        "total": odds.get("overUnder"),
        "lines_source": (odds.get("provider") or {}).get("name"),
    }


def scoreboard(dates: str) -> list[dict]:
    """dates = YYYYMMDD (ESPN currently rejects ranges with HTTP 400)."""
    status, data, _ = client().get_json(f"{SITE}/scoreboard", params={"dates": dates, "limit": 1000})
    if status != 200 or not data:
        raise RuntimeError(f"ESPN scoreboard unavailable for {dates} (HTTP {status})")
    out = []
    for e in data.get("events", []):
        try:
            out.append(parse_event(e))
        except (KeyError, IndexError, ValueError):
            continue  # exhibition / All-Star style events without standard team records
    return out


def _int(x: str) -> int:
    try:
        return int(x)
    except (TypeError, ValueError):
        return 0


def _made_att(x: str) -> tuple[int, int]:
    try:
        m, a = x.split("-")
        return int(m), int(a)
    except (AttributeError, ValueError):
        return 0, 0


def parse_summary(d: dict) -> dict:
    """Box score -> player rows, team rows, starters, closing-ish game lines."""
    hdr = d["header"]["competitions"][0]
    comp = {c["homeAway"]: c for c in hdr["competitors"]}
    periods = max(len(comp["home"].get("linescores", [])), len(comp["away"].get("linescores", []))) or None
    players, teams = [], []
    team_home = {}
    for t in d["boxscore"].get("teams", []):
        team_home[t["team"]["id"]] = t["homeAway"] == "home"
    for block in d["boxscore"].get("players", []):
        tid = block["team"]["id"]
        st = block["statistics"][0] if block.get("statistics") else None
        if not st:
            continue
        keys = st.get("names") or st.get("labels")
        for a in st.get("athletes", []):
            ath = a.get("athlete") or {}
            if not ath.get("id"):
                continue
            row = {"athlete_id": ath["id"], "name": ath["displayName"],
                   "position": (ath.get("position") or {}).get("abbreviation"), "team_id": tid,
                   "starter": bool(a.get("starter")), "dnp": bool(a.get("didNotPlay")) or not a.get("stats"),
                   "dnp_reason": a.get("reason") or None}
            vals = dict(zip(keys, a.get("stats") or []))
            fgm, fga = _made_att(vals.get("FG"))
            f3m, f3a = _made_att(vals.get("3PT"))
            ftm, fta = _made_att(vals.get("FT"))
            row.update(minutes=float(_int(vals.get("MIN"))), pts=_int(vals.get("PTS")), reb=_int(vals.get("REB")),
                       ast=_int(vals.get("AST")), fg3m=f3m, fg3a=f3a, fgm=fgm, fga=fga, ftm=ftm, fta=fta,
                       oreb=_int(vals.get("OREB")), dreb=_int(vals.get("DREB")), stl=_int(vals.get("STL")),
                       blk=_int(vals.get("BLK")), tov=_int(vals.get("TO")), pf=_int(vals.get("PF")),
                       plus_minus=_int(str(vals.get("+/-", "0")).replace("+", "")))
            if row["minutes"] <= 0 and not row["dnp"]:
                row["dnp"] = True
            players.append(row)
    for t in d["boxscore"].get("teams", []):
        sv = {s["name"]: s["displayValue"] for s in t.get("statistics", [])}
        fgm, fga = _made_att(sv.get("fieldGoalsMade-fieldGoalsAttempted"))
        f3m, f3a = _made_att(sv.get("threePointFieldGoalsMade-threePointFieldGoalsAttempted"))
        ftm, fta = _made_att(sv.get("freeThrowsMade-freeThrowsAttempted"))
        teams.append({"team_id": t["team"]["id"], "home": t["homeAway"] == "home", "fga": fga, "fta": fta,
                      "oreb": _int(sv.get("offensiveRebounds")), "tov": _int(sv.get("totalTurnovers") or sv.get("turnovers")),
                      "reb": _int(sv.get("totalRebounds")), "ast": _int(sv.get("assists")), "fg3m": f3m, "fg3a": f3a,
                      "stl": _int(sv.get("steals")), "blk": _int(sv.get("blocks"))})
    scores = {c["team"]["id"]: _int(c.get("score")) for c in hdr["competitors"]}
    home_abbr = comp["home"]["team"]["abbreviation"]
    away_abbr = comp["away"]["team"]["abbreviation"]
    pc = (d.get("pickcenter") or [{}])[0]
    return {
        "completed": bool(hdr["status"]["type"].get("completed")),
        "periods": periods,
        "players": players,
        "teams": teams,
        "scores": scores,
        "spread_home": parse_spread(pc.get("details"), home_abbr, away_abbr),
        "total": pc.get("overUnder"),
        "lines_source": (pc.get("provider") or {}).get("name"),
    }


def summary(game_id: str) -> dict | None:
    status, data, _ = client().get_json(f"{SITE}/summary", params={"event": game_id})
    if status != 200 or not data:
        return None
    return parse_summary(data)


def injuries() -> tuple[list[dict], datetime, str]:
    url = f"{SITE}/injuries"
    status, data, _ = client().get_json(url)
    if status != 200 or not data:
        raise RuntimeError(f"ESPN injuries unavailable (HTTP {status})")
    out = []
    for team in data.get("injuries", []):
        for i in team.get("injuries", []):
            ath = i.get("athlete", {})
            aid = None
            for link in ath.get("links", []):
                m = re.search(r"/id/(\d+)", link.get("href", ""))
                if m:
                    aid = m.group(1)
                    break
            if not aid:
                continue
            out.append({"team_id": team.get("id"), "athlete_id": aid, "athlete_name": ath.get("displayName", ""),
                        "status": i.get("status", "Unknown"), "reported_at": _parse_dt(i["date"]) if i.get("date") else None,
                        "comment": i.get("shortComment") or i.get("longComment")})
    return out, datetime.now(timezone.utc).replace(tzinfo=None), url


def _ip(american: int) -> float:
    return 100 / (american + 100) if american > 0 else -american / (-american + 100)


def _american(x) -> int | None:
    try:
        v = str(x).strip().upper()
        if v in ("EVEN", "EV"):
            return 100
        return int(v.replace("+", ""))
    except (TypeError, ValueError):
        return None


def parse_propbets(items: list[dict], game_id: str, retrieved_at: datetime, url: str, historical: bool) -> list[dict]:
    """Normalize ESPN propBets items into one row per quoted side.

    ESPN lists the two sides of a main line as two unlabeled items. Their order is over then under,
    which we verify per pair against the same player's alternate-line ladder (an 'X+' milestone
    is an over at X-0.5). Pairs whose ladder contradicts the order are marked 'contradicted' and
    are excluded downstream; pairs that cannot be checked are 'order_only'.
    """
    rows = []
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for it in items:
        if "athlete" not in it:
            continue
        aid = it["athlete"]["$ref"].split("/athletes/")[1].split("?")[0]
        groups[(aid, it["type"]["name"])].append(it)

    def base(it, aid):
        upd = it.get("lastUpdated")
        return {"game_id": game_id, "athlete_id": aid, "retrieved_at": retrieved_at, "source": "espn_dk",
                "book": "DraftKings", "quote_updated_at": _parse_dt(upd) if upd else None,
                "is_historical_close": historical, "source_url": url}

    ladders: dict[tuple[str, str], dict[float, float]] = defaultdict(dict)
    for (aid, tname), lst in groups.items():
        if tname in ALT_MARKETS:
            mkt = ALT_MARKETS[tname]
            for it in lst:
                tgt = (it.get("current") or {}).get("target", {}).get("value")
                am = _american(it["odds"]["american"].get("value"))
                if tgt is None or am is None:
                    continue
                ladders[(aid, mkt)][float(tgt)] = _ip(am)
                # ESPN's "open" on ladder rungs repeats the main line's opening quote, so it is not stored.
                rows.append({**base(it, aid), "market": mkt, "kind": "alt", "line": float(tgt) - 0.5, "side": "over",
                             "american": am, "open_line": None, "open_american": None,
                             "side_verification": "labeled"})
        elif tname in YES_MARKETS:
            for it in lst:
                am = _american(it["odds"]["american"].get("value"))
                if am is None:
                    continue
                rows.append({**base(it, aid), "market": YES_MARKETS[tname], "kind": "yes_no", "line": 0.5, "side": "yes",
                             "american": am, "open_line": 0.5, "open_american": _american(it["odds"]["american"].get("open")),
                             "side_verification": "labeled"})

    for (aid, tname), lst in groups.items():
        if tname not in MAIN_MARKETS:
            continue
        mkt = MAIN_MARKETS[tname]
        if len(lst) != 2:
            continue  # one-sided or malformed main line: cannot establish sides
        sides = []
        for it in lst:
            line = (it.get("current") or {}).get("target", {}).get("value")
            am = _american(it["odds"]["american"].get("value"))
            sides.append((it, line, am))
        if any(s[1] is None or s[2] is None for s in sides) or sides[0][1] != sides[1][1]:
            continue
        line = float(sides[0][1])
        p0, p1 = _ip(sides[0][2]), _ip(sides[1][2])
        verification = "order_only"
        ladder_p = ladders.get((aid, mkt), {}).get(float(math.ceil(line)))
        if ladder_p is not None and abs(p0 - p1) >= 0.03:
            verification = "ladder_verified" if abs(ladder_p - p0) < abs(ladder_p - p1) else "contradicted"
        for (it, _, am), side in zip(sides, ("over", "under")):
            otgt = (it.get("open") or {}).get("target", {}).get("value")
            rows.append({**base(it, aid), "market": mkt, "kind": "main", "line": line, "side": side, "american": am,
                         "open_line": float(otgt) if otgt is not None else None,
                         "open_american": _american(it["odds"]["american"].get("open")),
                         "side_verification": verification})
    return rows


def propbets(game_id: str, historical: bool = False) -> tuple[list[dict], str] | None:
    url = f"{CORE}/events/{game_id}/competitions/{game_id}/odds/{DK_PROVIDER_ID}/propBets"
    items, page, pages = [], 1, 1
    while page <= pages:
        status, data, _ = client().get_json(url, params={"lang": "en", "region": "us", "limit": 1000, "page": page})
        if status != 200 or not data:
            return None if page == 1 else (parse_propbets(items, game_id, datetime.now(timezone.utc).replace(tzinfo=None), url, historical), url)
        items.extend(data.get("items", []))
        pages = data.get("pageCount", 1) or 1
        page += 1
    return parse_propbets(items, game_id, datetime.now(timezone.utc).replace(tzinfo=None), url, historical), url
