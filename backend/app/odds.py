"""Odds arithmetic. Pure functions; covered by tests/test_odds.py."""
from __future__ import annotations


def american_to_decimal(a: int) -> float:
    return 1 + (a / 100 if a > 0 else 100 / -a)


def decimal_to_american(d: float) -> int:
    if d <= 1:
        raise ValueError("decimal odds must exceed 1")
    return round((d - 1) * 100) if d >= 2 else round(-100 / (d - 1))


def implied_prob(a: int) -> float:
    """Break-even probability of a price (includes the book's margin)."""
    return 1 / american_to_decimal(a)


def no_vig_two_way(a_side: int, a_other: int) -> tuple[float, float]:
    """Multiplicative (proportional) de-vig of a two-way market. Returns (p_side, overround)."""
    p1, p2 = implied_prob(a_side), implied_prob(a_other)
    return p1 / (p1 + p2), p1 + p2 - 1


def fair_american(p: float) -> int | None:
    if p <= 0 or p >= 1:
        return None
    return decimal_to_american(1 / p)


def ev_per_unit(p_win: float, a: int, p_push: float = 0.0) -> float:
    """Expected profit per 1 unit staked. A push returns the stake (profit 0)."""
    profit = american_to_decimal(a) - 1
    p_loss = 1 - p_win - p_push
    return p_win * profit - p_loss


def profit_if(result: str, a: int, stake: float = 1.0) -> float:
    if result == "win":
        return stake * (american_to_decimal(a) - 1)
    if result == "loss":
        return -stake
    return 0.0  # push / void


def settle(actual: float, line: float, side: str) -> str:
    if side == "yes":
        return "win" if actual >= 1 else "loss"
    if actual == line:
        return "push"
    over = actual > line
    return "win" if (over if side == "over" else not over) else "loss"
