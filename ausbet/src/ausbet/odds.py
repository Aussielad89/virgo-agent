"""Odds parsing and conversion across all common formats.

Canonical internal representation is **decimal odds** (>= 1.0), the standard
for Australian bookmakers.

Supported formats:
    decimal     1.50                        (profit 0.50 per 1.00 staked)
    fractional  1/2, 5-2                    (UK/IRL style)
    american    +150 / -200                 (US style)
    hk          0.50                        (Hong Kong: profit per 1 staked)
    indo        +2.00 / -1.25               (Indonesian: +/- profit/stake-to-win-1)
    malay       +0.50 / -0.80               (Malaysian: +/- profit/stake-to-win-1)

Auto-detection covers decimal / fractional / american only — HK, Indo and
Malay values are ambiguous with decimal and each other, so those must be
passed explicitly with ``fmt=``.
"""

from __future__ import annotations

from fractions import Fraction

FORMATS = ("decimal", "fractional", "american", "hk", "indo", "malay")

# Formats that can be auto-detected from a bare string.
_AUTO_DETECTABLE = ("decimal", "fractional", "american")


def parse(value: str | float | int, fmt: str | None = None) -> float:
    """Parse an odds representation into decimal odds (>= 1.0)."""
    if isinstance(value, (int, float)):
        if isinstance(value, bool):
            raise ValueError("bool is not an odds value")
        d = float(value)
    else:
        s = str(value).strip()
        if not s:
            raise ValueError("empty odds string")
        if fmt is None:
            if "/" in s:
                fmt = "fractional"
            elif s.startswith("+") or s.startswith("-"):
                fmt = "american"
            elif "-" in s and all(part.replace(".", "", 1).isdigit() for part in s.split("-")):
                fmt = "fractional"  # US style "5-2"
            elif _is_plain_decimal(s):
                fmt = "decimal"
            else:
                raise ValueError(
                    f"cannot auto-detect format for {value!r}; pass --from "
                    f"(one of {', '.join(_AUTO_DETECTABLE)}, or hk/indo/malay explicitly)"
                )
        fmt = fmt.lower()
        if fmt == "decimal":
            d = float(s)
        elif fmt == "fractional":
            s = s.replace("-", "/")  # "5-2" -> "5/2"
            num, _, den = s.partition("/")
            if not den:
                raise ValueError(f"fractional odds must look like '3/2', got {value!r}")
            d = 1.0 + float(num) / float(den)
        elif fmt == "american":
            v = float(s)
            d = 1.0 + v / 100.0 if v > 0 else 1.0 + 100.0 / abs(v)
        elif fmt == "hk":
            d = 1.0 + float(s)
        elif fmt == "indo":
            v = float(s)
            d = 1.0 + v if v > 0 else 1.0 + 1.0 / abs(v)
        elif fmt == "malay":
            v = float(s)
            d = 1.0 + v if v > 0 else 1.0 + 1.0 / abs(v)
        else:
            raise ValueError(f"unknown format {fmt!r}; one of {', '.join(FORMATS)}")
    if d < 1.0:
        raise ValueError(f"odds must be >= 1.0, got {d}")
    return round(d, 4)


def _is_plain_decimal(s: str) -> bool:
    return s.replace(".", "", 1).isdigit()


def format_odds(decimal: float, fmt: str) -> str:
    """Render decimal odds in the requested format."""
    fmt = fmt.lower()
    d = float(decimal)
    if d < 1.0:
        raise ValueError(f"odds must be >= 1.0, got {d}")
    if fmt == "decimal":
        return f"{d:.2f}"
    if fmt == "fractional":
        f = Fraction(d - 1.0).limit_denominator(1000)
        return f"{f.numerator}/{f.denominator}"
    if fmt == "american":
        if d >= 2.0:
            return f"+{round((d - 1.0) * 100)}"
        return f"-{round(100.0 / (d - 1.0))}"
    if fmt == "hk":
        return f"{d - 1.0:.2f}"
    if fmt == "indo":
        v = d - 1.0
        if d >= 2.0:
            return f"{v:+.2f}"
        return f"{(-1.0 / v):.2f}"
    if fmt == "malay":
        v = d - 1.0
        if d <= 2.0:
            return f"{v:+.2f}"
        return f"{(-1.0 / v):.2f}"
    raise ValueError(f"unknown format {fmt!r}; one of {', '.join(FORMATS)}")


def convert(value: str | float | int, to: str, fmt: str | None = None) -> str:
    """Convert an odds value to another format, returning the formatted string."""
    return format_odds(parse(value, fmt=fmt), to)


def implied_probability(decimal: float) -> float:
    """Bookmaker-implied win probability from decimal odds (0..1)."""
    return 1.0 / float(decimal)


def overround_pct(odds: list[float]) -> float:
    """Bookmaker margin: sum of implied probabilities * 100. >100 = bookie edge."""
    return sum(1.0 / o for o in odds) * 100.0
