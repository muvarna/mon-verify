from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from .clients.wos import is_research_commons_record, normalize_wos_record, wos_records_from_payload
from .dedup import canonical_id_for, group_records
from .incites import QuartileIndex
from .manual import apply_manual_overrides, load_manual_overrides
from .models import CanonicalPublication, MinistryClaim, SourceRecord
from .normalization import normalize_doi, normalize_title
from .omega import omega_records
from .rules import RuleEngine
from .scival import SciValIndex, SciValPublication, normalize_scopus_identifier


def _first(group: list[SourceRecord], attr: str, priority: tuple[str, ...] = ("wos", "omega")) -> Any:
    for source in priority:
        for record in group:
            if record.source != source:
                continue
            value = getattr(record, attr)
            if value not in (None, "", [], {}):
                return value
    for record in group:
        value = getattr(record, attr)
        if value not in (None, "", [], {}):
            return value
    return None


def _load_json(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def source_records_from_wos_json(path: str | Path, organization: str = "Medical University Varna") -> list[SourceRecord]:
    payload = _load_json(path)
    query = str(payload.get("query", "")) if isinstance(payload, dict) else ""
    query_affiliation_evidence = "OG=" in query.upper() and organization.lower() in query.lower()
    pages = payload.get("pages") if isinstance(payload, dict) else None
    raw_records = (
        [record for page in pages if isinstance(page, dict) for record in wos_records_from_payload(page)]
        if isinstance(pages, list)
        else wos_records_from_payload(payload)
    )
    raw_records = [record for record in raw_records if not is_research_commons_record(record)]
    records = [normalize_wos_record(record, organization=organization) for record in raw_records]
    if query_affiliation_evidence:
        for record in records:
            if record.muv_affiliation is None:
                record.muv_affiliation = True
    return records


def _preferred_year(group: list[SourceRecord]) -> int | None:
    for source in ("wos", "omega"):
        for record in group:
            if record.source == source and record.year is not None:
                return record.year
    return next((record.year for record in group if record.year is not None), None)


def _scival_match(group: list[SourceRecord], index: SciValIndex | None) -> tuple[SciValPublication | None, str | None]:
    if index is None:
        return None, None
    return index.match(
        scopus_id=_first(group, "scopus_id"),
        doi=_first(group, "doi"),
        title=_first(group, "title"),
        year=_preferred_year(group),
    )


def _legacy_scival_count(group: list[SourceRecord], lookup: dict[tuple[str, str], int] | None) -> int | None:
    if not lookup:
        return None
    for record in group:
        for sid in (record.scopus_eid, record.scopus_id):
            if sid and ("scopus", sid) in lookup:
                return lookup[("scopus", sid)]
    for record in group:
        doi = normalize_doi(record.doi)
        if doi and ("doi", doi) in lookup:
            return lookup[("doi", doi)]
    for record in group:
        title = normalize_title(record.title)
        if title and record.year is not None:
            key = f"{title}|{record.year}"
            if ("title_year", key) in lookup:
                return lookup[("title_year", key)]
    return None


def merge_group(
    group: list[SourceRecord],
    *,
    quartiles: QuartileIndex,
    rules: RuleEngine,
    scival_index: SciValIndex | None = None,
    scival_lookup: dict[tuple[str, str], int] | None = None,
) -> CanonicalPublication:
    title = _first(group, "title")
    issn = _first(group, "issn")
    eissn = _first(group, "eissn")
    source_title = _first(group, "source_title")
    quartile = quartiles.match(issn, eissn, source_title)

    wos_records = [r for r in group if r.source == "wos"]
    omega_records_ = [r for r in group if r.source == "omega"]
    wos_count = next((r.institution_count for r in wos_records if r.institution_count is not None and r.institution_count > 0), None)

    scival_row, scival_match_method = _scival_match(group, scival_index)
    scival_count = scival_row.institution_count if scival_row else _legacy_scival_count(group, scival_lookup)
    original_omega_scopus_id = next((r.scopus_id for r in omega_records_ if r.scopus_id), None)
    original_sid = normalize_scopus_identifier(original_omega_scopus_id)

    if scival_row:
        scopus_id = scival_row.scopus_id
        scopus_eid = scival_row.eid
    else:
        scopus_id = normalize_scopus_identifier(_first(group, "scopus_id"))
        scopus_eid = f"2-s2.0-{scopus_id}" if scopus_id else None

    if wos_count is not None:
        selected_count, count_source = wos_count, "wos"
    elif scival_count is not None and scival_count > 0:
        selected_count, count_source = scival_count, "scival"
    else:
        selected_count, count_source = None, None

    bucket = rules.bucket_for_quartile(quartile.quartile)
    multiplier = rules.multiplier(selected_count)
    score_contribution = multiplier * rules.bucket_weight(bucket) if multiplier is not None else None

    omega_q = next((r.omega_jif_quartile for r in omega_records_ if r.omega_jif_quartile), None)
    omega_authors = next((r.omega_authors for r in omega_records_ if r.omega_authors), None)
    omega_original: dict[str, Any] = {}
    for record in omega_records_:
        row = (record.raw or {}).get("omega_row") if isinstance(record.raw, dict) else None
        if isinstance(row, dict):
            omega_original = dict(row)
            break

    muv_authors_wos = sorted(
        {name.strip() for record in wos_records for name in record.muv_authors if name and name.strip()},
        key=str.lower,
    )

    discrepancies: list[str] = []
    if omega_q and quartile.quartile and omega_q != quartile.quartile:
        discrepancies.append("QUARTILE_MISMATCH")
    if quartile.method is None:
        discrepancies.append("JOURNAL_NOT_IN_JCR")
    elif quartile.method == "title_fuzzy" or quartile.confidence in {"manual_review", "ambiguous"}:
        discrepancies.append("QUARTILE_AMBIGUOUS")
    if wos_count is not None and scival_count is not None and wos_count != scival_count:
        discrepancies.append("INSTITUTION_COUNT_MISMATCH")
    if scival_row and original_sid and original_sid != scival_row.scopus_id:
        discrepancies.append("SCOPUS_ID_CORRECTED_FROM_SCIVAL")
    elif scival_row and not original_sid:
        discrepancies.append("SCOPUS_ID_ADDED_FROM_SCIVAL")
    if wos_records and not omega_records_:
        discrepancies.extend(["WOS_ONLY", "MISSING_FROM_OMEGA"])

    years = {r.source: r.year for r in group if r.year is not None}
    if scival_row and scival_row.year is not None:
        years["scival"] = scival_row.year
    if len(set(years.values())) > 1:
        discrepancies.append("YEAR_MISMATCH")

    wos_ut = _first(group, "wos_ut")
    has_identifier = bool(wos_ut or scopus_id or scopus_eid)
    eligible = True if has_identifier and selected_count is not None else None
    if selected_count is None:
        eligibility_reason = "Institution count missing or zero; manual review required"
        discrepancies.append("MISSING_INSTITUTION_COUNT")
    elif has_identifier:
        eligibility_reason = "WoS and/or Scopus identifier present with institution count"
    else:
        eligibility_reason = "No WoS or Scopus identifier"

    status = "confirmed" if eligible is True else "manual_review"
    if status == "confirmed" and discrepancies:
        status = "strongly_supported"

    evidence_urls = sorted({r.evidence_url for r in group if r.evidence_url})
    if scopus_eid:
        evidence_urls.append(f"https://www.scopus.com/record/display.uri?eid={scopus_eid}&origin=resultslist")
        evidence_urls = sorted(set(evidence_urls))

    provenance = [
        {
            "source": r.source,
            "source_id": r.source_id,
            "year": r.year,
            "institution_count": r.institution_count,
            "muv_authors": r.muv_authors,
            "evidence_url": r.evidence_url,
        }
        for r in group
    ]
    if scival_row:
        provenance.append({
            "source": "scival",
            "source_id": scival_row.eid,
            "year": scival_row.year,
            "institution_count": scival_row.institution_count,
            "match_method": scival_match_method,
            "evidence_url": f"https://www.scopus.com/record/display.uri?eid={scival_row.eid}&origin=resultslist",
        })

    return CanonicalPublication(
        canonical_id=canonical_id_for(group),
        doi=_first(group, "doi") or (scival_row.doi if scival_row else None),
        wos_ut=wos_ut,
        scopus_id=scopus_id,
        scopus_eid=scopus_eid,
        original_omega_scopus_id=original_omega_scopus_id,
        scival_match_method=scival_match_method,
        title=title or (scival_row.title if scival_row else None),
        normalized_title=normalize_title(title or (scival_row.title if scival_row else None)),
        source_years=years,
        document_type=_first(group, "document_type"),
        source_title=source_title,
        issn=issn,
        eissn=eissn,
        in_omega=bool(omega_records_),
        in_wos=bool(wos_records),
        in_scopus=bool(scival_row or scopus_id),
        eligible_for_calculation=eligible,
        eligibility_reason=eligibility_reason,
        muv_affiliation_wos=next((r.muv_affiliation for r in wos_records if r.muv_affiliation is not None), None),
        omega_authors=omega_authors,
        muv_authors_wos=muv_authors_wos,
        omega_original=omega_original,
        omega_jif_quartile=omega_q,
        jif_quartile=quartile.quartile,
        quartile_match_method=quartile.method,
        quartile_match_confidence=quartile.confidence,
        wos_institution_count=wos_count,
        scival_institution_count=scival_count,
        selected_institution_count=selected_count,
        institution_count_source=count_source,
        over_10_institutions=rules.is_over_threshold(selected_count),
        ministry_bucket=bucket,
        contribution_multiplier=multiplier,
        weighted_contribution=multiplier,
        score_contribution=score_contribution,
        discrepancy_codes=sorted(set(discrepancies)),
        verification_status=status,
        evidence_urls=evidence_urls,
        provenance=provenance,
    )


def _flag_title_identifier_conflicts(publications: list[CanonicalPublication]) -> None:
    by_title: dict[tuple[str, int | None], list[CanonicalPublication]] = {}
    for pub in publications:
        years = [y for y in pub.source_years.values() if y is not None]
        year = years[0] if years else None
        if pub.normalized_title:
            by_title.setdefault((pub.normalized_title, year), []).append(pub)
    for group in by_title.values():
        if len(group) < 2:
            continue
        dois = {normalize_doi(p.doi) for p in group if normalize_doi(p.doi)}
        wos_ids = {p.wos_ut for p in group if p.wos_ut}
        scopus_ids = {p.scopus_id for p in group if p.scopus_id}
        for pub in group:
            if len(dois) > 1:
                pub.discrepancy_codes = sorted(set(pub.discrepancy_codes + ["DOI_CONFLICT", "TITLE_CONFLICT"]))
            elif len(wos_ids) > 1 or len(scopus_ids) > 1:
                pub.discrepancy_codes = sorted(set(pub.discrepancy_codes + ["TITLE_CONFLICT"]))


def _path_list(value: str | Path | list[str | Path] | tuple[str | Path, ...] | None) -> list[str | Path]:
    if value is None:
        return []
    if isinstance(value, (str, Path)):
        return [value]
    return list(value)


def build_canonical_publications(
    *,
    omega_path: str | Path,
    quartiles_path: str | Path,
    rules_path: str | Path,
    wos_json: str | Path | list[str | Path] | tuple[str | Path, ...] | None = None,
    scival_csv: str | Path | None = None,
    manual_overrides_csv: str | Path | None = None,
    **_: object,
) -> list[CanonicalPublication]:
    rules = RuleEngine.from_yaml(rules_path)
    raw_records: list[SourceRecord] = omega_records(omega_path)
    wos_org = str(rules.rules["wos"]["organization_enhanced"])
    wos_paths = _path_list(wos_json)
    for path in wos_paths:
        raw_records.extend(source_records_from_wos_json(path, organization=wos_org))

    scival_index = SciValIndex.from_csv(scival_csv) if scival_csv else None
    quartile_index = QuartileIndex.from_csv(quartiles_path)
    groups = group_records(raw_records)
    publications = [merge_group(g, quartiles=quartile_index, rules=rules, scival_index=scival_index) for g in groups]

    wos_attempted = bool(wos_paths)
    for pub in publications:
        if wos_attempted and pub.in_omega and not pub.in_wos and pub.wos_ut:
            pub.discrepancy_codes = sorted(set(pub.discrepancy_codes + ["NOT_FOUND_IN_WOS_API"]))

    _flag_title_identifier_conflicts(publications)
    if manual_overrides_csv:
        publications = apply_manual_overrides(publications, rules, load_manual_overrides(manual_overrides_csv))

    return sorted(
        publications,
        key=lambda x: (
            1 if x.manually_removed else 0,
            1 if x.selected_institution_count is None else 0,
            (x.source_title or "").casefold(),
            (x.title or "").casefold(),
            x.canonical_id,
        ),
    )


def aggregate(publications: Iterable[CanonicalPublication], rules: RuleEngine) -> dict[str, Any]:
    pubs = list(publications)
    buckets = ("a1", "a2", "a3", "a4")
    raw = {bucket: 0 for bucket in buckets}
    weighted = {bucket: 0.0 for bucket in buckets}
    unresolved = {bucket: 0 for bucket in buckets}
    over_10 = {bucket: 0 for bucket in buckets}
    removed = 0

    for pub in pubs:
        if pub.manually_removed:
            removed += 1
            continue
        bucket = pub.ministry_bucket if pub.ministry_bucket in buckets else "a4"
        if pub.selected_institution_count is None:
            unresolved[bucket] += 1
            continue
        raw[bucket] += 1
        weighted[bucket] += float(pub.weighted_contribution or 0.0)
        if pub.over_10_institutions is True:
            over_10[bucket] += 1

    weighted = {k: round(v, 10) for k, v in weighted.items()}
    publication_count = sum(raw.values())
    a_score = round(float(rules.score(weighted)), 10)
    unresolved_count = sum(unresolved.values())
    return {
        "candidate_publication_count": len(pubs),
        "publication_count": publication_count,
        "confirmed_publication_count": publication_count,
        "excluded_publication_count": removed,
        "removed_publication_count": removed,
        "unresolved_eligibility_count": unresolved_count,
        "unresolved_institution_count": unresolved_count,
        "raw": raw,
        "raw_confirmed": dict(raw),
        "unresolved_eligibility_by_bucket": unresolved,
        "weighted": weighted,
        "weighted_known": dict(weighted),
        "unresolved_weight_count": dict(unresolved),
        "over_10": over_10,
        "a_score": a_score,
        "calculation_complete": unresolved_count == 0,
        "eligibility_complete": unresolved_count == 0,
        "weight_complete": unresolved_count == 0,
        "calculation_note": "Complete calculation" if unresolved_count == 0 else "Confirmed subtotal only; unresolved records lack institution counts",
    }


def compare_to_ministry(publications: Iterable[CanonicalPublication], claim: MinistryClaim, rules: RuleEngine) -> list[dict[str, Any]]:
    calc = aggregate(publications, rules)
    rows = [
        ("publication_count", claim.publication_count, calc["publication_count"]),
        ("q1_raw", claim.q1_raw, calc["raw"]["a1"]),
        ("q1_weighted", claim.q1_weighted, calc["weighted"]["a1"]),
        ("q2_raw", claim.q2_raw, calc["raw"]["a2"]),
        ("q2_weighted", claim.q2_weighted, calc["weighted"]["a2"]),
        ("q3_raw", claim.q3_raw, calc["raw"]["a3"]),
        ("q3_weighted", claim.q3_weighted, calc["weighted"]["a3"]),
        ("a4_raw", claim.a4_raw, calc["raw"]["a4"]),
        ("a4_weighted", claim.a4_weighted, calc["weighted"]["a4"]),
        ("a_score", claim.a_score, calc["a_score"]),
    ]
    return [
        {
            "metric": name,
            "ministry_claim": ministry,
            "calculated": calculated,
            "difference": calculated - ministry,
            "calculation_complete": calc["calculation_complete"],
            "note": calc["calculation_note"],
        }
        for name, ministry, calculated in rows
    ]
