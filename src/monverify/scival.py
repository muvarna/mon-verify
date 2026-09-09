from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from .normalization import empty_to_none, normalize_doi, normalize_title

DEFAULT_COUNT_COLUMN = "Number of Institutions"
DEFAULT_DOI_COLUMN = "DOI"
DEFAULT_SCOPUS_COLUMN = "EID"
DEFAULT_TITLE_COLUMN = "Title"
DEFAULT_YEAR_COLUMN = "Year"


def _detect_header_row(path: str | Path, *, required: tuple[str, ...] = ("EID", "Number of Institutions")) -> int:
    with Path(path).open("r", encoding="utf-8-sig", errors="replace", newline="") as handle:
        for index, line in enumerate(handle):
            if index > 100:
                break
            try:
                fields = next(csv.reader([line]))
            except csv.Error:
                continue
            normalized = {str(value).strip() for value in fields}
            if all(name in normalized for name in required):
                return index
    raise ValueError(
        "Could not locate the SciVal publication table header. Expected columns include "
        f"{', '.join(required)}."
    )


def load_scival(path: str | Path) -> pd.DataFrame:
    header_row = _detect_header_row(path)
    frame = pd.read_csv(path, skiprows=header_row, dtype=str, encoding="utf-8-sig", keep_default_na=False)
    frame.columns = [str(c).strip() for c in frame.columns]
    if DEFAULT_SCOPUS_COLUMN in frame.columns:
        frame = frame[frame[DEFAULT_SCOPUS_COLUMN].astype(str).str.strip().ne("")].copy()
    return frame.reset_index(drop=True)


def normalize_scopus_identifier(value: object) -> str | None:
    text = empty_to_none(value)
    if not text:
        return None
    text = str(text).strip()
    if text.upper().startswith("SCOPUS_ID:"):
        text = text.split(":", 1)[1].strip()
    if text.lower().startswith("2-s2.0-"):
        text = text[len("2-s2.0-") :]
    return text or None


def canonical_scopus_eid(value: object) -> str | None:
    sid = normalize_scopus_identifier(value)
    return f"2-s2.0-{sid}" if sid else None


@dataclass(frozen=True)
class SciValPublication:
    eid: str
    scopus_id: str
    doi: str | None
    title: str | None
    normalized_title: str | None
    year: int | None
    institution_count: int | None


class SciValIndex:
    def __init__(self, rows: list[SciValPublication]):
        self.rows = rows
        self.by_scopus: dict[str, SciValPublication] = {}
        doi_candidates: dict[str, list[SciValPublication]] = {}
        title_candidates: dict[str, list[SciValPublication]] = {}
        for row in rows:
            self.by_scopus[row.scopus_id] = row
            self.by_scopus[row.eid] = row
            if row.doi:
                doi_candidates.setdefault(row.doi, []).append(row)
            if row.normalized_title and row.year is not None:
                title_candidates.setdefault(f"{row.normalized_title}|{row.year}", []).append(row)
        self.by_doi = {k: v[0] for k, v in doi_candidates.items() if len(v) == 1}
        self.by_title_year = {k: v[0] for k, v in title_candidates.items() if len(v) == 1}

    @classmethod
    def from_csv(cls, path: str | Path) -> "SciValIndex":
        frame = load_scival(path)
        rows: list[SciValPublication] = []
        for _, row in frame.iterrows():
            sid = normalize_scopus_identifier(row.get(DEFAULT_SCOPUS_COLUMN))
            if not sid:
                continue
            eid = f"2-s2.0-{sid}"
            doi = normalize_doi(row.get(DEFAULT_DOI_COLUMN))
            title = empty_to_none(row.get(DEFAULT_TITLE_COLUMN))
            normalized_title = normalize_title(title)
            year_text = empty_to_none(row.get(DEFAULT_YEAR_COLUMN))
            try:
                year = int(float(str(year_text))) if year_text else None
            except ValueError:
                year = None
            count_text = empty_to_none(row.get(DEFAULT_COUNT_COLUMN))
            try:
                count = int(float(str(count_text).replace(",", "").strip())) if count_text else None
            except ValueError:
                count = None
            if count is not None and count <= 0:
                count = None
            rows.append(SciValPublication(eid, sid, doi, title, normalized_title, year, count))
        return cls(rows)

    def match(self, *, scopus_id: object = None, doi: object = None, title: object = None, year: int | None = None) -> tuple[SciValPublication | None, str | None]:
        # DOI is preferred over a possibly stale/wrong OMEGA Scopus ID. This lets
        # SciVal correct OMEGA identifiers rather than accepting a conflicting ID.
        nd = normalize_doi(doi)
        if nd and nd in self.by_doi:
            return self.by_doi[nd], "doi"
        sid = normalize_scopus_identifier(scopus_id)
        if sid and sid in self.by_scopus:
            return self.by_scopus[sid], "scopus_id"
        nt = normalize_title(title)
        if nt and year is not None:
            key = f"{nt}|{year}"
            if key in self.by_title_year:
                return self.by_title_year[key], "title_year"
        return None, None


def load_scival_counts(path: str | Path, **_: object) -> dict[tuple[str, str], int]:
    index = SciValIndex.from_csv(path)
    out: dict[tuple[str, str], int] = {}
    for row in index.rows:
        if row.institution_count is None:
            continue
        out[("scopus", row.scopus_id)] = row.institution_count
        out[("scopus", row.eid)] = row.institution_count
        if row.doi:
            out[("doi", row.doi)] = row.institution_count
        if row.normalized_title and row.year is not None:
            out[("title_year", f"{row.normalized_title}|{row.year}")] = row.institution_count
    return out


def inspect_scival(path: str | Path) -> dict[str, object]:
    frame = load_scival(path)
    counts = pd.to_numeric(frame.get(DEFAULT_COUNT_COLUMN), errors="coerce")
    return {
        "rows": int(len(frame)),
        "columns": list(frame.columns),
        "year_values": sorted({x for x in frame.get(DEFAULT_YEAR_COLUMN, pd.Series(dtype=str)).astype(str) if x}),
        "with_doi": int(frame.get(DEFAULT_DOI_COLUMN, pd.Series(dtype=str)).astype(str).str.strip().replace("-", "").ne("").sum()),
        "with_eid": int(frame.get(DEFAULT_SCOPUS_COLUMN, pd.Series(dtype=str)).astype(str).str.strip().ne("").sum()),
        "zero_or_missing_institutions": int((counts.fillna(0) <= 0).sum()),
        "over_10_institutions": int((counts > 10).sum()),
        "max_institutions": int(counts.max()) if counts.notna().any() else None,
    }
