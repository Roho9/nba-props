from datetime import datetime

from app.providers.espn import parse_propbets, parse_spread, slate_date_of


def _item(aid, tname, american, target, open_t=None):
    disp = f"{int(target)}+" if "Milestones" in tname else str(target)
    return {"athlete": {"$ref": f"http://x/seasons/2027/athletes/{aid}?lang=en"}, "type": {"name": tname},
            "odds": {"american": {"value": str(american), "open": str(american)}, "total": {"value": disp}},
            "lastUpdated": "2026-11-25T08:56Z", "current": {"target": {"value": target}},
            "open": {"target": {"value": open_t if open_t is not None else target}}}


def test_spread_parse_home_perspective():
    assert parse_spread("PHI -1.5", "PHI", "MIA") == -1.5
    assert parse_spread("MIA -3", "PHI", "MIA") == 3.0
    assert parse_spread("EVEN", "PHI", "MIA") == 0.0
    assert parse_spread("garbage", "PHI", "MIA") is None


def test_slate_date_is_eastern():
    assert slate_date_of(datetime(2026, 11, 26, 3, 0)) == "2026-11-25"


def test_sides_verified_against_ladder():
    items = [_item(1, "Total Points", -140, 20.5), _item(1, "Total Points", 110, 20.5),
             _item(1, "Points Milestones", -150, 21.0)]
    rows = parse_propbets(items, "g", datetime(2026, 1, 1), "u", False)
    main = [r for r in rows if r["kind"] == "main"]
    assert {r["side"]: r["american"] for r in main} == {"over": -140, "under": 110}
    assert all(r["side_verification"] == "ladder_verified" for r in main)
    alt = [r for r in rows if r["kind"] == "alt"][0]
    assert alt["line"] == 20.5 and alt["side"] == "over"


def test_contradicted_order_is_flagged():
    # ladder says 21+ is about -150, which matches the SECOND item, so the feed order would be wrong
    items = [_item(1, "Total Points", 110, 20.5), _item(1, "Total Points", -140, 20.5),
             _item(1, "Points Milestones", -150, 21.0)]
    rows = parse_propbets(items, "g", datetime(2026, 1, 1), "u", False)
    assert all(r["side_verification"] == "contradicted" for r in rows if r["kind"] == "main")


def test_unverifiable_pair_is_order_only():
    items = [_item(1, "Total Assists", -115, 5.5), _item(1, "Total Assists", -105, 5.5)]
    rows = parse_propbets(items, "g", datetime(2026, 1, 1), "u", False)
    assert all(r["side_verification"] == "order_only" for r in rows)


def test_one_sided_main_is_dropped():
    rows = parse_propbets([_item(1, "Total Points", -110, 20.5)], "g", datetime(2026, 1, 1), "u", False)
    assert rows == []
