"""Odds parsing / conversion tests."""

from __future__ import annotations

import pytest

from ausbet.odds import (
    convert,
    format_odds,
    implied_probability,
    overround_pct,
    parse,
)


@pytest.mark.parametrize(
    ("value", "fmt", "expected"),
    [
        ("1.85", None, 1.85),
        (2.5, None, 2.5),
        (2, None, 2.0),
        ("5/2", None, 3.5),
        ("1/2", None, 1.5),
        ("5-2", None, 3.5),
        ("+150", None, 2.5),
        ("-200", None, 1.5),
        ("0.50", "hk", 1.5),
        ("+2.00", "indo", 3.0),
        ("-1.25", "indo", 1.8),
        ("+0.50", "malay", 1.5),
        ("-0.80", "malay", 2.25),
        ("11/4", "fractional", 3.75),
    ],
)
def test_parse(value, fmt, expected):
    assert parse(value, fmt=fmt) == pytest.approx(expected, abs=1e-4)


def test_parse_rejects_odds_below_1():
    with pytest.raises(ValueError):
        parse("0.50")  # ambiguous bare value fails cleanly


def test_parse_rejects_unknown_format():
    with pytest.raises(ValueError):
        parse("1.50", fmt="banana")


def test_parse_rejects_empty():
    with pytest.raises(ValueError):
        parse("   ")


def test_parse_rejects_bool():
    with pytest.raises(ValueError):
        parse(True)


@pytest.mark.parametrize(
    ("decimal", "fmt", "expected"),
    [
        (2.5, "decimal", "2.50"),
        (3.5, "fractional", "5/2"),
        (2.0, "fractional", "1/1"),
        (2.5, "american", "+150"),
        (1.5, "american", "-200"),
        (1.5, "hk", "0.50"),
        (3.0, "indo", "+2.00"),
        (1.8, "indo", "-1.25"),
        (1.8, "malay", "+0.80"),
        (5.0, "malay", "-0.25"),
    ],
)
def test_format_odds(decimal, fmt, expected):
    assert format_odds(decimal, fmt) == expected


@pytest.mark.parametrize("decimal", [1.5, 1.8, 2.0, 2.5, 3.0, 5.0, 11.0, 1.909])
@pytest.mark.parametrize("fmt", ["decimal", "fractional", "american", "hk", "indo", "malay"])
def test_round_trip_all_formats(decimal, fmt):
    rendered = format_odds(decimal, fmt)
    back = parse(rendered, fmt=fmt)
    assert back == pytest.approx(decimal, abs=0.011)


def test_convert_shortcut():
    assert convert("+150", "fractional") == "3/2"
    assert convert("5/2", "american", fmt="fractional") == "+250"


def test_implied_probability():
    assert implied_probability(2.0) == pytest.approx(0.5)
    assert implied_probability(4.0) == pytest.approx(0.25)


def test_overround_pct():
    assert overround_pct([2.0, 2.0]) == pytest.approx(100.0)
    assert overround_pct([1.90, 2.10]) == pytest.approx(100.25, abs=0.01)
    assert overround_pct([2.10, 2.05]) == pytest.approx(96.40, abs=0.01)
