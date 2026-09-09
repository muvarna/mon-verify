from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from .clients.wos import is_research_commons_record, normalize_wos_record, wos_records_from_payload
from .dedup import canonical_id_for, group_records
from .incites import QuartileIndex
from .models import CanonicalPublication, MinistryClaim, SourceRecord
from .normalization import normalize_doi, normalize_title
from .omega import omega_records
from .rules import RuleEngine
from .scival import load_scival_counts


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


def _scival_count_for(group: list[SourceRecord], lookup: dict[tuple[str, str], int] | None) -> int | None:
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
        if record.wos_ut and ("wos", record.wos_ut.upper()) in lookup:
            return lookup[("wos", record.wos_ut.upper())]
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
    scival_lookup: dict[tuple[str, str], int] | None = None,
) -> CanonicalPublication:
    title = _first(group, "title")
    issn = _first(group, "issn")
    eissn = _first(group, "eissn")
    source_title = _first(group, "source_title")
    quartile = quartiles.match(issn, eissn, source_title)

    wos_records = [r for r in group if r.source == "wos"]
    omega_records_ = [r for r in group if r.source == "omega"]

    wos_count = next((r.institution_count for r in wos_records if r.institution_count is not None), None)
    scival_count = _scival_count_for(group, scival_lookup)
    if wos_count is not None:
        selected_count, count_source = wos_count, "wos"
    elif scival_count is not None:
        selected_count, count_source = scival_count, "scival"
    else:
        selected_count, count_source = None, None

    bucket = rules.bucket_for_quartile(quartile.quartile)
    multiplier = rules.multiplier(selected_count)
    score_contribution = (multiplier * rules.bucket_weight(bucket)) if multiplier is not None else None

    omega_q = next((r.omega_jif_quartile for r in omega_records_ if r.omega_jif_quartile), None)
    omega_authors = next((r.omega_authors for r in omega_records_ if r.omega_authors), None)
    omega_original: dict[str, Any] = {}
    for record in omega_records_:
        raw = record.raw or {}
        row = raw.get("omega_row") if isinstance(raw, dict) else None
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
    if wos_records and not omega_records_:
        discrepancies.append("WOS_ONLY")

    years = {r.source: r.year for r in group if r.year is not None}
    if len(set(years.values())) > 1:
        discrepancies.append("YEAR_MISMATCH")

    muv_wos = next((r.muv_affiliation for r in wos_records if r.muv_affiliation is not None), None)
    if muv_wos is False:
        discrepancies.append("AFFILIATION_MISMATCH")

    wos_years = [r.year for r in wos_records if r.year is not None]
    has_target_year = any(y == rules.assessment_year for y in wos_years)
    if wos_records and muv_wos is True and has_target_year:
        eligible = True
        eligibility_reason = "WoS evidence confirms MU-Varna affiliation and target year"
    elif wos_records and muv_wos is False:
        eligible = False
        eligibility_reason = "WoS evidence does not confirm MU-Varna affiliation"
    elif wos_records and wos_years and all(y != rules.assessment_year for y in wos_years):
        eligible = False
        eligibility_reason = "WoS year is outside assessment year"
    else:
        eligible = None
        eligibility_reason = "WoS evidence is incomplete" if wos_records else "OMEGA seed has not yet been independently verified in WoS"

    evidence_urls = sorted({r.evidence_url for r in group if r.evidence_url})
    status = "confirmed"
    if eligible is False:
        status = "excluded"
    elif eligible is None or quartile.confidence in {"manual_review", "ambiguous", "unresolved"} or selected_count is None:
        status = "manual_review"
    elif discrepancies:
        status = "strongly_supported"

    return CanonicalPublication(
        canonical_id=canonical_id_for(group),
        doi=_first(group, "doi"),
        wos_ut=_first(group, "wos_ut"),
        scopus_id=_first(group, "scopus_id"),
        scopus_eid=_first(group, "scopus_eid"),
        title=title,
        normalized_title=normalize_title(title),
        source_years=years,
        document_type=_first(group, "document_type"),
        source_title=source_title,
        issn=issn,
        eissn=eissn,
        in_omega=bool(omega_records_),
        in_wos=bool(wos_records),
        in_scopus=False,
        eligible_for_calculation=eligible,
        eligibility_reason=eligibility_reason,
        muv_affiliation_wos=muv_wos,
        muv_affiliation_scopus=None,
        omega_authors=omega_authors,
        muv_authors_wos=muv_authors_wos,
        omega_original=omega_original,
        omega_jif_quartile=omega_q,
        jif_quartile=quartile.quartile,
        quartile_match_method=quartile.method,
        quartile_match_confidence=quartile.confidence,
        wos_institution_count=wos_count,
        scopus_institution_count=None,
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
        provenance=[
            {
                "source": r.source,
                "source_id": r.source_id,
                "year": r.year,
                "institution_count": r.institution_count,
                "muv_authors": r.muv_authors,
                "evidence_url": r.evidence_url,
            }
            for r in group
        ],
    )


def _flag_title_identifier_conflicts(publications: list[CanonicalPublication]) -> None:
    by_title: dict[tuple[str, int | None], list[CanonicalPublication]] = {}
    for pub in publications:
        title = pub.normalized_title
        years = [y for y in pub.source_years.values() if y is not None]
        year = years[0] if years else None
        if title:
            by_title.setdefault((title, year), []).append(pub)
    for group in by_title.values():
        if len(group) < 2:
            continue
        dois = {normalize_doi(p.doi) for p in group if normalize_doi(p.doi)}
        wos_ids = {p.wos_ut for p in group if p.wos_ut}
        for pub in group:
            if len(dois) > 1:
                pub.discrepancy_codes = sorted(set(pub.discrepancy_codes + ["DOI_CONFLICT", "TITLE_CONFLICT"]))
            elif len(wos_ids) > 1:
                pub.discrepancy_codes = sorted(set(pub.discrepancy_codes + ["TITLE_CONFLICT"]))
            if "TITLE_CONFLICT" in pub.discrepancy_codes:
                pub.verification_status = "manual_review"


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
    scival_count_column: str | None = None,
    scival_doi_column: str | None = None,
    scival_wos_column: str | None = None,
    scival_scopus_column: str | None = None,
) -> list[CanonicalPublication]:
    rules = RuleEngine.from_yaml(rules_path)
    raw_records: list[SourceRecord] = omega_records(omega_path)
    wos_org = str(rules.rules["wos"]["organization_enhanced"])
    wos_paths = _path_list(wos_json)
    for path in wos_paths:
        raw_records.extend(source_records_from_wos_json(path, organization=wos_org))

    scival_lookup = None
    if scival_csv:
        scival_lookup = load_scival_counts(
            scival_csv,
            count_column=scival_count_column,
            doi_column=scival_doi_column,
            wos_column=scival_wos_column,
            scopus_column=scival_scopus_column,
        )

    quartile_index = QuartileIndex.from_csv(quartiles_path)
    groups = group_records(raw_records)
    publications = [merge_group(g, quartiles=quartile_index, rules=rules, scival_lookup=scival_lookup) for g in groups]
    wos_attempted = bool(wos_paths)
    for pub in publications:
        if not pub.in_omega and pub.in_wos:
            pub.discrepancy_codes = sorted(set(pub.discrepancy_codes + ["MISSING_FROM_OMEGA", "WOS_ONLY"]))
        if wos_attempted and pub.in_omega and not pub.in_wos:
            pub.discrepancy_codes = sorted(set(pub.discrepancy_codes + ["OMEGA_ONLY"]))
            if pub.wos_ut:
                pub.discrepancy_codes = sorted(set(pub.discrepancy_codes + ["NOT_FOUND_IN_API"]))
    _flag_title_identifier_conflicts(publications)
    return sorted(publications, key=lambda x: ((x.title or "").lower(), x.canonical_id))


def aggregate(publications: Iterable[CanonicalPublication], rules: RuleEngine) -> dict[str, Any]:
    """Return numeric confirmed subtotals even while some records remain unresolved.

    Previous versions returned null for an entire bucket whenever that bucket also
    contained an unresolved publication. That made the Streamlit summary unusable.
    This function now always reports the auditable confirmed subtotal and separately
    reports unresolved eligibility/weight counts plus completeness flags.
    """
    pubs = list(publications)
    buckets = ("a1", "a2", "a3", "a4")
    raw = {bucket: 0 for bucket in buckets}
    unresolved_eligibility = {bucket: 0 for bucket in buckets}
    weighted = {bucket: 0.0 for bucket in buckets}
    unresolved_weight = {bucket: 0 for bucket in buckets}
    over_10 = {bucket: 0 for bucket in buckets}
    excluded = 0

    for pub in pubs:
        bucket = pub.ministry_bucket if pub.ministry_bucket in buckets else "a4"
        if pub.eligible_for_calculation is False:
            excluded += 1
            continue
        if pub.eligible_for_calculation is None:
            unresolved_eligibility[bucket] += 1
            continue

        raw[bucket] += 1
        if pub.weighted_contribution is None:
            unresolved_weight[bucket] += 1
        else:
            weighted[bucket] += float(pub.weighted_contribution)
        if pub.over_10_institutions is True:
            over_10[bucket] += 1

    weighted = {k: round(v, 10) for k, v in weighted.items()}
    publication_count = sum(raw.values())
    a_score = rules.score(weighted)
    eligibility_complete = sum(unresolved_eligibility.values()) == 0
    weight_complete = sum(unresolved_weight.values()) == 0

    return {
        "candidate_publication_count": len(pubs),
        "publication_count": publication_count,
        "confirmed_publication_count": publication_count,
        "excluded_publication_count": excluded,
        "unresolved_eligibility_count": sum(unresolved_eligibility.values()),
        "raw": raw,
        "raw_confirmed": dict(raw),
        "unresolved_eligibility_by_bucket": unresolved_eligibility,
        "weighted": weighted,
        "weighted_known": dict(weighted),
        "unresolved_weight_count": unresolved_weight,
        "over_10": over_10,
        "a_score": round(float(a_score), 10),
        "calculation_complete": eligibility_complete and weight_complete,
        "eligibility_complete": eligibility_complete,
        "weight_complete": weight_complete,
        "calculation_note": (
            "Complete calculation" if eligibility_complete and weight_complete
            else "Confirmed subtotal only; unresolved records are reported separately"
        ),
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
