"""Gemini's free tier may not serve users in the EEA, Switzerland or the UK (§B10, §B18)."""

from __future__ import annotations

EEA_CH_UK: frozenset[str] = frozenset(
    "AT BE BG HR CY CZ DK EE FI FR DE GR HU IE IT LV LT LU MT NL PL PT RO SK SI ES SE "
    "IS LI NO CH GB UK".split()
)


def gemini_free_allowed(country: str | None, *, unknown_allowed: bool = False) -> bool:
    """Unknown country fails closed when deployed (Vercel always sends x-vercel-ip-country);
    local dev and internal jobs may pass unknown_allowed=True or an explicit country."""
    if not country:
        return unknown_allowed
    return country.upper() not in EEA_CH_UK
