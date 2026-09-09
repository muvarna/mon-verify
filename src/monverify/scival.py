from __future__ import annotations

from pathlib import Path

import pandas as pd

from .normalization import empty_to_none, normalize_doi


def load_scival_counts(path: str | Path, *, count_column: str, doi_column: str | None = None, wos_column: str | None = None, scopus_column: str | None = None) -> dict[tuple[str, str], int]:
    frame = pd.read_csv(path, dtype=str, encoding="utf-8-sig", keep_default_na=False)
    for column in [count_column, doi_column, wos_column, scopus_column]:
        if column and column not in frame.columns:
            raise ValueError(f"SciVal CSV missing requested column: {column}")
    if not any([doi_column, wos_column, scopus_column]):
        raise ValueError("Supply at least one SciVal identifier column")
    out: dict[tuple[str, str], int] = {}
    for _, row in frame.iterrows():
        count_text = empty_to_none(row.get(count_column))
        if not count_text:
            continue
        count = int(float(count_text))
        if doi_column:
            doi = normalize_doi(row.get(doi_column))
            if doi:
                out[("doi", doi)] = count
        if wos_column:
            value = empty_to_none(row.get(wos_column))
            if value:
                out[("wos", value.upper())] = count
        if scopus_column:
            value = empty_to_none(row.get(scopus_column))
            if value:
                out[("scopus", value)] = count
    return out
