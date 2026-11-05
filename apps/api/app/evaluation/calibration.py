"""Agreement is computed only from genuine labels; conflicting consensus ties are excluded."""

from typing import Any


def calibration(pairs: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(pairs)
    if not n:
        return {
            "sample_size": 0,
            "agreement": None,
            "kappa": None,
            "false_passes": [],
            "false_fails": [],
            "message": "Insufficient human labels",
        }
    agree = sum(p["human"] == p["judge"] for p in pairs) / n
    hp = sum(p["human"] for p in pairs) / n
    jp = sum(p["judge"] for p in pairs) / n
    chance = hp * jp + (1 - hp) * (1 - jp)
    return {
        "sample_size": n,
        "agreement": agree,
        "kappa": (agree - chance) / (1 - chance) if chance < 1 else None,
        "false_passes": [p["id"] for p in pairs if p["judge"] and not p["human"]],
        "false_fails": [p["id"] for p in pairs if not p["judge"] and p["human"]],
        "message": "Kappa undefined when chance agreement is 1"
        if chance == 1
        else "Observed agreement; small samples are not a reliability guarantee",
    }
