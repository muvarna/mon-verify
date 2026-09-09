from __future__ import annotations

import csv
from pathlib import Path

import pandas as pd

from .normalization import empty_to_none, normalize_doi, normalize_title

DEFAULT_COUNT_COLUMN = "Number of Institutions"
DEFAULT_DOI_COLUMN = "DOI"
DEFAULT_SCOPUS_COLUMN = "EID"
DEFAULT_TITLE_COLUMN = "Title"
DEFAULT_YEAR_COLUMN = "Year"


def _detect_header_row(path: str | Path, *, required: tuple[str, ...] = ("EID", "Number of Institutions")) -> int:
    """Return the zero-based row containing the actual SciVal table header."""
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
    """Load a SciVal publication export, automatically skipping its metadata preamble."""
    header_row = _detect_header_row(path)
    frame = pd.read_csv(
        path,
        skiprows=header_row,
        dtype=str,
        encoding="utf-8-sig",
        keep_default_na=False,
    )
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


def load_scival_counts(
    path: str | Path,
    *,
    count_column: str | None = None,
    doi_column: str | None = None,
    wos_column: str | None = None,
    scopus_column: str | None = None,
    title_column: str | None = None,
    year_column: str | None = None,
) -> dict[tuple[str, str], int]:
    """Load institution counts from SciVal.

    The standard MU-Varna SciVal export is auto-detected. Matching keys are built
    for Scopus EID/ID and DOI. Exact normalized title + year is indexed only when
    unambiguous.
    """
    frame = load_scival(path)
    count_column = count_column or DEFAULT_COUNT_COLUMN
    doi_column = doi_column or (DEFAULT_DOI_COLUMN if DEFAULT_DOI_COLUMN in frame.columns else None)
    scopus_column = scopus_column or (DEFAULT_SCOPUS_COLUMN if DEFAULT_SCOPUS_COLUMN in frame.columns else None)
    title_column = title_column or (DEFAULT_TITLE_COLUMN if DEFAULT_TITLE_COLUMN in frame.columns else None)
    year_column = year_column or (DEFAULT_YEAR_COLUMN if DEFAULT_YEAR_COLUMN in frame.columns else None)

    for column in [count_column, doi_column, wos_column, scopus_column, title_column, year_column]:
        if column and column not in frame.columns:
            raise ValueError(f"SciVal CSV missing requested column: {column}")
    if not any([doi_column, wos_column, scopus_column, title_column]):
        raise ValueError("SciVal export has no usable publication identifier columns")

    out: dict[tuple[str, str], int] = {}
    title_year_candidates: dict[str, set[int]] = {}

    for _, row in frame.iterrows():
        count_text = empty_to_none(row.get(count_column))
        if not count_text:
            continue
        try:
            count = int(float(str(count_text).replace(",", "").strip()))
        except ValueError as exc:
            raise ValueError(f"Invalid SciVal institution count: {count_text!r}") from exc
        if count < 1:
            continue

        if doi_column:
            doi = normalize_doi(row.get(doi_column))
            if doi:
                out[("doi", doi)] = count

        if wos_column:
            value = empty_to_none(row.get(wos_column))
            if value:
                out[("wos", str(value).upper())] = count

        if scopus_column:
            raw = empty_to_none(row.get(scopus_column))
            if raw:
                raw_text = str(raw).strip()
                out[("scopus", raw_text)] = count
                sid = normalize_scopus_identifier(raw_text)
                if sid:
                    out[("scopus", sid)] = count
                    out[("scopus", f"2-s2.0-{sid}")] = count

        if title_column and year_column:
            title = normalize_title(row.get(title_column))
            year_text = empty_to_none(row.get(year_column))
            if title and year_text:
                try:
                    year = int(float(str(year_text)))
                except ValueError:
                    year = None
                if year is not None:
                    key = f"{title}|{year}"
                    title_year_candidates.setdefault(key, set()).add(count)

    for key, counts in title_year_candidates.items():
        if len(counts) == 1:
            out[("title_year", key)] = next(iter(counts))
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
        "over_10_institutions": int((counts > 10).sum()),
        "max_institutions": int(counts.max()) if counts.notna().any() else None,
    }
