from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

from .models import SourceRecord
from .normalization import empty_to_none, normalize_doi, normalize_issn, normalize_quartile, normalize_title

EXPECTED_COLUMNS = {
    "Reference",
    "Journal",
    "publicationType",
    "Issue year",
    "DOI",
    "WoSId",
    "ScopusId",
    "JIFQuartile",
    "Authors MU-Varna",
    "Link WOS",
    "Link Scopus",
}


def load_omega(path: str | Path) -> pd.DataFrame:
    frame = pd.read_csv(path, dtype=str, encoding="utf-8-sig", keep_default_na=False)
    frame.columns = [c.strip() for c in frame.columns]
    missing = sorted(EXPECTED_COLUMNS - set(frame.columns))
    if missing:
        raise ValueError(f"OMEGA CSV missing columns: {missing}")
    return frame


def parse_journal_field(value: object) -> tuple[str | None, str | None, str | None]:
    text = empty_to_none(value)
    if not text:
        return None, None, None
    title_match = re.match(r"^(.*?)(?:,\s*ISSN\b|$)", text, flags=re.I)
    title = title_match.group(1).strip() if title_match else text.strip()
    issn_match = re.search(r"(?<!e-)\bISSN\s+([0-9]{4}-?[0-9Xx]{4})", text, flags=re.I)
    eissn_match = re.search(r"\be-ISSN\s+([0-9]{4}-?[0-9Xx]{4})", text, flags=re.I)
    return title or None, normalize_issn(issn_match.group(1)) if issn_match else None, normalize_issn(eissn_match.group(1)) if eissn_match else None


def extract_title(reference: object, journal_title: str | None) -> str | None:
    ref = empty_to_none(reference)
    if not ref:
        return None
    body = ref.split(" : ", 1)[1] if " : " in ref else ref
    if journal_title:
        pattern = re.compile(r",\s*" + re.escape(journal_title) + r"\s*,\s*20\d{2}\b", flags=re.I)
        m = pattern.search(body)
        if m:
            return body[:m.start()].strip(" ,") or None
    m = re.search(r",\s*[^,]+,\s*20\d{2}\b", body)
    return body[:m.start()].strip(" ,") if m else body.strip()


def omega_records(path: str | Path) -> list[SourceRecord]:
    frame = load_omega(path)
    records: list[SourceRecord] = []
    for idx, row in frame.iterrows():
        journal_title, issn, eissn = parse_journal_field(row.get("Journal"))
        title = extract_title(row.get("Reference"), journal_title)
        year_text = empty_to_none(row.get("Issue year"))
        year = int(float(year_text)) if year_text else None
        wos_ut = empty_to_none(row.get("WoSId"))
        scopus_id = empty_to_none(row.get("ScopusId"))
        doi = normalize_doi(row.get("DOI"))
        records.append(
            SourceRecord(
                source="omega",
                source_id=f"omega:{idx + 1}",
                doi=doi,
                wos_ut=wos_ut,
                scopus_id=scopus_id,
                title=title,
                normalized_title=normalize_title(title),
                year=year,
                document_type=empty_to_none(row.get("publicationType")),
                source_title=journal_title,
                issn=issn,
                eissn=eissn,
                omega_jif_quartile=normalize_quartile(row.get("JIFQuartile")),
                omega_authors=empty_to_none(row.get("Authors MU-Varna")),
                evidence_url=empty_to_none(row.get("Link WOS")) or empty_to_none(row.get("Link Scopus")),
                raw={"row_number": int(idx + 2)},
            )
        )
    return records
