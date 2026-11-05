"""Citation parsing and validation (§B7, §B8.1). A citation is a pointer, not proof."""

from __future__ import annotations

import re
from dataclasses import dataclass

_CITE = re.compile(r"\[(\d{1,3})\]")
NOT_IN_DATA = "The answer is not in the provided data."


@dataclass(frozen=True)
class CitationReport:
    used: list[int]
    invalid: list[int]
    uncited: bool

    @property
    def valid(self) -> bool:
        return not self.invalid and not self.uncited


def check_citations(answer: str, n_sources: int) -> CitationReport:
    nums = [int(m) for m in _CITE.findall(answer)]
    used = sorted({n for n in nums if 1 <= n <= n_sources})
    invalid = sorted({n for n in nums if not 1 <= n <= n_sources})
    declined = NOT_IN_DATA.lower().rstrip(".") in answer.lower()
    return CitationReport(used, invalid, uncited=not used and not declined)
