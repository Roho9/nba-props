import math

import pytest

from app.odds import (american_to_decimal, decimal_to_american, ev_per_unit, fair_american, implied_prob,
                      no_vig_two_way, profit_if, settle)


def test_american_decimal_roundtrip():
    for a in (-500, -250, -110, -105, 100, 105, 150, 400):
        assert decimal_to_american(american_to_decimal(a)) == a


def test_implied_and_breakeven():
    assert implied_prob(-110) == pytest.approx(110 / 210)
    assert implied_prob(150) == pytest.approx(0.4)


def test_no_vig_sums_to_one_and_reports_overround():
    p, over = no_vig_two_way(-110, -110)
    assert p == pytest.approx(0.5)
    assert over == pytest.approx(2 * 110 / 210 - 1)
    p1, _ = no_vig_two_way(-150, 120)
    p2, _ = no_vig_two_way(120, -150)
    assert p1 + p2 == pytest.approx(1.0)


def test_ev_zero_at_break_even_and_push_handling():
    assert ev_per_unit(implied_prob(-120), -120) == pytest.approx(0.0, abs=1e-12)
    # a push returns the stake, so it reduces both win and loss mass
    assert ev_per_unit(0.5, 100, p_push=0.2) == pytest.approx(0.5 - 0.3)


def test_high_probability_can_be_negative_ev():
    assert ev_per_unit(0.85, -830) < 0


def test_fair_american():
    assert fair_american(0.5) == 100
    assert fair_american(0.0) is None


def test_settlement():
    assert settle(21, 20.5, "over") == "win"
    assert settle(20, 20.5, "over") == "loss"
    assert settle(20, 20.5, "under") == "win"
    assert settle(20, 20.0, "over") == "push"
    assert settle(1, 0.5, "yes") == "win"
    assert profit_if("win", -110) == pytest.approx(100 / 110)
    assert profit_if("void", -110) == 0
