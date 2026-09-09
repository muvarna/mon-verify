from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd
from rapidfuzz import fuzz, process

from .normalization import normalize_issn, normalize_quartile, normalize_title

EXPECTED_COLUMNS = {"Name", "ISSN", "eISSN", "Journal Impact Factor", "JIF Quartile"}


@dataclass(slots=True)
class QuartileMatch:
    quartile: str | None
    method: str | None
    confidence: str
    matched_name: str | None = None
    score: float | None = None


class QuartileIndex:
    def __init__(self, frame: pd.DataFrame):
        self.frame = frame.copy()
        self.frame.columns = [c.strip() for c in self.frame.columns]
        missing = sorted(EXPECTED_COLUMNS - set(self.frame.columns))
        if missing:
            raise ValueError(f"JCR/InCites CSV missing columns: {missing}")
        self.frame["_issn"] = self.frame["ISSN"].map(normalize_issn)
        self.frame["_eissn"] = self.frame["eISSN"].map(normalize_issn)
        self.frame["_title"] = self.frame["Name"].map(normalize_title)
        self.frame["_quartile"] = self.frame["JIF Quartile"].map(normalize_quartile)
        self._issn = self._make_index("_issn")
        self._eissn = self._make_index("_eissn")
        self._title = self._make_index("_title")
        self._title_choices = [x for x in self.frame["_title"].dropna().unique().tolist() if x]

    @classmethod
    def from_csv(cls, path: str | Path) -> "QuartileIndex":
        return cls(pd.read_csv(path, dtype=str, encoding="utf-8-sig", keep_default_na=False))

    def _make_index(self, column: str) -> dict[str, list[int]]:
        out: dict[str, list[int]] = {}
        for idx, value in self.frame[column].items():
            if value:
                out.setdefault(value, []).append(int(idx))
        return out

    def _resolve(self, indices: list[int], method: str) -> QuartileMatch:
        rows = self.frame.loc[indices]
        # Re-normalize here because pandas may coerce None values produced by
        # Series.map() back to floating NaN. NaN is truthy, so filtering with
        # `if q` alone can incorrectly treat it as a real quartile.
        quartiles = sorted(
            {
                normalized
                for raw in rows["_quartile"].tolist()
                if (normalized := normalize_quartile(raw)) is not None
            }
        )
        matched_name = normalize_title(rows.iloc[0]["Name"])
        display_name = str(rows.iloc[0]["Name"]) if matched_name else None
        if len(quartiles) == 1:
            return QuartileMatch(quartiles[0], method, "confirmed", display_name, 100.0)
        if len(quartiles) == 0:
            return QuartileMatch(None, method, "confirmed", display_name, 100.0)
        return QuartileMatch(None, method, "ambiguous", display_name, 100.0)

    def match(self, issn: str | None, eissn: str | None, title: str | None, fuzzy_threshold: float = 94.0) -> QuartileMatch:
        for method, raw, index in (("issn", issn, self._issn), ("eissn", eissn, self._eissn)):
            value = normalize_issn(raw)
            if value and value in index:
                return self._resolve(index[value], method)
        ntitle = normalize_title(title)
        if ntitle and ntitle in self._title:
            return self._resolve(self._title[ntitle], "title_exact")
        if ntitle and self._title_choices:
            found = process.extractOne(ntitle, self._title_choices, scorer=fuzz.ratio)
            if found and float(found[1]) >= fuzzy_threshold:
                matched_title, score, _ = found
                rows = self.frame.loc[self._title[matched_title]]
                return QuartileMatch(None, "title_fuzzy", "manual_review", str(rows.iloc[0]["Name"]), float(score))
        return QuartileMatch(None, None, "unresolved")
