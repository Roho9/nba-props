from datetime import datetime

from app.providers.odds_api import norm_name, parse_event_odds


def test_name_normalization():
    assert norm_name("Luka Dončić") == norm_name("Luka Doncic")
    assert norm_name("Jaren Jackson Jr.") == norm_name("Jaren Jackson")


def test_parse_labeled_outcomes_and_unmatched():
    data = {"bookmakers": [{"key": "fanduel", "title": "FanDuel", "markets": [{"key": "player_points", "last_update": "2026-11-25T18:00:00Z",
            "outcomes": [{"name": "Over", "description": "Jalen Brunson", "price": -115, "point": 26.5},
                         {"name": "Under", "description": "Jalen Brunson", "price": -105, "point": 26.5},
                         {"name": "Over", "description": "Unknown Guy", "price": 100, "point": 3.5}]}]}]}
    rows, unmatched = parse_event_odds(data, "g1", {norm_name("Jalen Brunson"): "42"}, datetime(2026, 11, 25), "https://x/odds?apiKey=SECRET")
    assert {(r["side"], r["american"]) for r in rows} == {("over", -115), ("under", -105)}
    assert unmatched == ["Unknown Guy"]
    assert all("SECRET" not in r["source_url"] for r in rows)
    assert all(r["book"] == "FanDuel" and r["side_verification"] == "labeled" for r in rows)
