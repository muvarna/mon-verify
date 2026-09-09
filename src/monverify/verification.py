from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from .clients.scopus import normalize_scopus_abstract, normalize_scopus_entry, scopus_entries_from_payload
from .clients.wos import normalize_wos_record, wos_records_from_payload
from .dedup import canonical_id_for, group_records
from .incites import QuartileIndex
from .models import CanonicalPublication, MinistryClaim, SourceRecord
from .normalization import normalize_doi, normalize_title
from .omega import omega_records
from .rules import RuleEngine
from .scival import load_scival_counts


def _first(group: list[SourceRecord], attr: str, priority: tuple[str, ...] = ("wos", "scopus", "omega")) -> Any:
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
    raw_records = ([record for page in pages if isinstance(page, dict) for record in wos_records_from_payload(page)] if isinstance(pages, list) else wos_records_from_payload(payload))
    records = [normalize_wos_record(record, organization=organization) for record in raw_records]
    if query_affiliation_evidence:
        for record in records:
            if record.muv_affiliation is None:
                record.muv_affiliation = True
    return records


def source_records_from_scopus_json(path: str | Path, affiliation_id: str = "60005828") -> list[SourceRecord]:
    payload = _load_json(path)
    query = str(payload.get("query", "")) if isinstance(payload, dict) else ""
    query_affiliation_evidence = f"AF-ID({affiliation_id})".replace(" ", "").lower() in query.replace(" ", "").lower()
    abstracts = payload.get("abstracts") if isinstance(payload, dict) else None
    if isinstance(abstracts, list):
        records = [normalize_scopus_abstract(item, affiliation_id=affiliation_id) for item in abstracts if isinstance(item, dict) and not item.get("_monverify_error")]
    else:
        pages = payload.get("pages") if isinstance(payload, dict) else None
        raw_entries = ([entry for page in pages if isinstance(page, dict) for entry in scopus_entries_from_payload(page)] if isinstance(pages, list) else scopus_entries_from_payload(payload))
        records = [normalize_scopus_entry(entry, affiliation_id=affiliation_id) for entry in raw_entries]
    if query_affiliation_evidence:
        for record in records:
            if record.muv_affiliation is None:
                record.muv_affiliation = True
    return records


def _scival_count_for(group: list[SourceRecord], lookup: dict[tuple[str, str], int] | None) -> int | None:
    if not lookup:
        return None
    for record in group:
        doi = normalize_doi(record.doi)
        if doi and ("doi", doi) in lookup:
            return lookup[("doi", doi)]
        if record.wos_ut and ("wos", record.wos_ut.upper()) in lookup:
            return lookup[("wos", record.wos_ut.upper())]
        for sid in (record.scopus_eid, record.scopus_id):
            if sid and ("scopus", sid) in lookup:
                return lookup[("scopus", sid)]
    return None


def merge_group(group: list[SourceRecord], *, quartiles: QuartileIndex, rules: RuleEngine, scival_lookup: dict[tuple[str, str], int] | None = None) -> CanonicalPublication:
    title = _first(group, "title")
    issn = _first(group, "issn")
    eissn = _first(group, "eissn")
    source_title = _first(group, "source_title")
    quartile = quartiles.match(issn, eissn, source_title)
    wos_records = [r for r in group if r.source == "wos"]
    scopus_records = [r for r in group if r.source == "scopus"]
    omega_records_ = [r for r in group if r.source == "omega"]
    wos_count = next((r.institution_count for r in wos_records if r.institution_count is not None), None)
    scopus_count = next((r.institution_count for r in scopus_records if r.institution_count is not None), None)
    scival_count = _scival_count_for(group, scival_lookup)
    if wos_count is not None:
        selected_count, count_source = wos_count, "wos"
    elif scopus_count is not None:
        selected_count, count_source = scopus_count, "scopus"
    elif scival_count is not None:
        selected_count, count_source = scival_count, "scival"
    else:
        selected_count, count_source = None, None
    bucket = rules.bucket_for_quartile(quartile.quartile)
    multiplier = rules.multiplier(selected_count)
    score_contribution = (multiplier * rules.bucket_weight(bucket)) if multiplier is not None else None
    omega_q = next((r.omega_jif_quartile for r in omega_records_ if r.omega_jif_quartile), None)
    discrepancies: list[str] = []
    if omega_q and quartile.quartile and omega_q != quartile.quartile:
        discrepancies.append("QUARTILE_MISMATCH")
    if quartile.method is None:
        discrepancies.append("JOURNAL_NOT_IN_JCR")
    elif quartile.method == "title_fuzzy" or quartile.confidence in {"manual_review", "ambiguous"}:
        discrepancies.append("QUARTILE_AMBIGUOUS")
    if wos_count is not None and scopus_count is not None and wos_count != scopus_count:
        discrepancies.append("INSTITUTION_COUNT_MISMATCH")
    if wos_records and not omega_records_:
        discrepancies.append("WOS_ONLY")
    if scopus_records and not omega_records_:
        discrepancies.append("SCOPUS_ONLY")
    years = {r.source: r.year for r in group if r.year is not None}
    if len(set(years.values())) > 1:
        discrepancies.append("YEAR_MISMATCH")
    muv_wos = next((r.muv_affiliation for r in wos_records if r.muv_affiliation is not None), None)
    muv_scopus = next((r.muv_affiliation for r in scopus_records if r.muv_affiliation is not None), None)
    if muv_wos is False or muv_scopus is False:
        discrepancies.append("AFFILIATION_MISMATCH")
    external_records = wos_records + scopus_records
    external_years = [r.year for r in external_records if r.year is not None]
    has_target_year = any(y == rules.assessment_year for y in external_years)
    affiliation_confirmed = (muv_wos is True) or (muv_scopus is True)
    affiliation_definitively_false = bool(external_records) and not affiliation_confirmed and all(r.muv_affiliation is False for r in external_records if r.muv_affiliation is not None) and any(r.muv_affiliation is not None for r in external_records)
    if external_records and affiliation_confirmed and has_target_year:
        eligible = True
        eligibility_reason = "External API evidence confirms MU-Varna affiliation and target year"
    elif external_records and affiliation_definitively_false:
        eligible = False
        eligibility_reason = "External API records do not confirm MU-Varna affiliation"
    elif external_records and external_years and not has_target_year and all(y != rules.assessment_year for y in external_years):
        eligible = False
        eligibility_reason = "External API year is outside assessment year"
    else:
        eligible = None
        eligibility_reason = "External API evidence is incomplete" if external_records else "OMEGA seed has not yet been independently verified"
    evidence_urls = sorted({r.evidence_url for r in group if r.evidence_url})
    status = "confirmed"
    if eligible is False:
        status = "excluded"
    elif eligible is None or quartile.confidence in {"manual_review", "ambiguous", "unresolved"} or selected_count is None:
        status = "manual_review"
    elif discrepancies:
        status = "strongly_supported"
    return CanonicalPublication(canonical_id=canonical_id_for(group),doi=_first(group, "doi"),wos_ut=_first(group, "wos_ut"),scopus_id=_first(group, "scopus_id"),scopus_eid=_first(group, "scopus_eid"),title=title,normalized_title=normalize_title(title),source_years=years,document_type=_first(group, "document_type"),source_title=source_title,issn=issn,eissn=eissn,in_omega=bool(omega_records_),in_wos=bool(wos_records),in_scopus=bool(scopus_records),eligible_for_calculation=eligible,eligibility_reason=eligibility_reason,muv_affiliation_wos=muv_wos,muv_affiliation_scopus=muv_scopus,omega_jif_quartile=omega_q,jif_quartile=quartile.quartile,quartile_match_method=quartile.method,quartile_match_confidence=quartile.confidence,wos_institution_count=wos_count,scopus_institution_count=scopus_count,scival_institution_count=scival_count,selected_institution_count=selected_count,institution_count_source=count_source,over_10_institutions=rules.is_over_threshold(selected_count),ministry_bucket=bucket,contribution_multiplier=multiplier,weighted_contribution=multiplier,score_contribution=score_contribution,discrepancy_codes=sorted(set(discrepancies)),verification_status=status,evidence_urls=evidence_urls,provenance=[{"source": r.source,"source_id": r.source_id,"year": r.year,"institution_count": r.institution_count,"evidence_url": r.evidence_url} for r in group])


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
        scopus_ids = {p.scopus_eid or p.scopus_id for p in group if (p.scopus_eid or p.scopus_id)}
        for pub in group:
            if len(dois) > 1:
                pub.discrepancy_codes = sorted(set(pub.discrepancy_codes + ["DOI_CONFLICT", "TITLE_CONFLICT"]))
            elif len(wos_ids) > 1 or len(scopus_ids) > 1:
                pub.discrepancy_codes = sorted(set(pub.discrepancy_codes + ["TITLE_CONFLICT"]))
            if "TITLE_CONFLICT" in pub.discrepancy_codes:
                pub.verification_status = "manual_review"


def _path_list(value: str | Path | list[str | Path] | tuple[str | Path, ...] | None) -> list[str | Path]:
    if value is None:
        return []
    if isinstance(value, (str, Path)):
        return [value]
    return list(value)


def build_canonical_publications(*, omega_path: str | Path, quartiles_path: str | Path, rules_path: str | Path, wos_json: str | Path | list[str | Path] | tuple[str | Path, ...] | None = None, scopus_json: str | Path | list[str | Path] | tuple[str | Path, ...] | None = None, scival_csv: str | Path | None = None, scival_count_column: str | None = None, scival_doi_column: str | None = None, scival_wos_column: str | None = None, scival_scopus_column: str | None = None) -> list[CanonicalPublication]:
    rules = RuleEngine.from_yaml(rules_path)
    raw_records: list[SourceRecord] = omega_records(omega_path)
    rule_data = rules.rules
    wos_org = str(rule_data["wos"]["organization_enhanced"])
    scopus_aff = str(rule_data["scopus"]["affiliation_id"])
    wos_paths = _path_list(wos_json)
    scopus_paths = _path_list(scopus_json)
    for path in wos_paths:
        raw_records.extend(source_records_from_wos_json(path, organization=wos_org))
    for path in scopus_paths:
        raw_records.extend(source_records_from_scopus_json(path, affiliation_id=scopus_aff))
    scival_lookup = None
    if scival_csv:
        if not scival_count_column:
            raise ValueError("--scival-count-column is required with a SciVal CSV")
        scival_lookup = load_scival_counts(scival_csv,count_column=scival_count_column,doi_column=scival_doi_column,wos_column=scival_wos_column,scopus_column=scival_scopus_column)
    quartile_index = QuartileIndex.from_csv(quartiles_path)
    groups = group_records(raw_records)
    publications = [merge_group(g, quartiles=quartile_index, rules=rules, scival_lookup=scival_lookup) for g in groups]
    api_verification_attempted = bool(wos_paths or scopus_paths)
    wos_attempted = bool(wos_paths)
    scopus_attempted = bool(scopus_paths)
    for pub in publications:
        if not pub.in_omega and (pub.in_wos or pub.in_scopus):
            pub.discrepancy_codes = sorted(set(pub.discrepancy_codes + ["MISSING_FROM_OMEGA"]))
        if api_verification_attempted and pub.in_omega and not pub.in_wos and not pub.in_scopus:
            pub.discrepancy_codes = sorted(set(pub.discrepancy_codes + ["OMEGA_ONLY"]))
            relevant_lookup_attempted = (wos_attempted and bool(pub.wos_ut)) or (scopus_attempted and bool(pub.scopus_id or pub.scopus_eid))
            if relevant_lookup_attempted:
                pub.discrepancy_codes = sorted(set(pub.discrepancy_codes + ["NOT_FOUND_IN_API"]))
    _flag_title_identifier_conflicts(publications)
    return sorted(publications, key=lambda x: ((x.title or "").lower(), x.canonical_id))


def aggregate(publications: Iterable[CanonicalPublication], rules: RuleEngine) -> dict[str, Any]:
    pubs = list(publications)
    buckets = ("a1", "a2", "a3", "a4")
    confirmed_raw = {bucket: 0 for bucket in buckets}
    unresolved_eligibility = {bucket: 0 for bucket in buckets}
    weighted_known = {bucket: 0.0 for bucket in buckets}
    unresolved_weight = {bucket: 0 for bucket in buckets}
    over_10 = {bucket: 0 for bucket in buckets}
    excluded = 0
    for pub in pubs:
        bucket = pub.ministry_bucket or "a4"
        if pub.eligible_for_calculation is False:
            excluded += 1
            continue
        if pub.eligible_for_calculation is None:
            unresolved_eligibility[bucket] += 1
            continue
        confirmed_raw[bucket] += 1
        if pub.weighted_contribution is None:
            unresolved_weight[bucket] += 1
        else:
            weighted_known[bucket] += float(pub.weighted_contribution)
        if pub.over_10_institutions:
            over_10[bucket] += 1
    raw = {bucket: (None if unresolved_eligibility[bucket] else confirmed_raw[bucket]) for bucket in buckets}
    weighted = {bucket: (None if unresolved_eligibility[bucket] or unresolved_weight[bucket] else round(weighted_known[bucket], 10)) for bucket in buckets}
    complete = all(v == 0 for v in unresolved_eligibility.values()) and all(v == 0 for v in unresolved_weight.values())
    score = rules.score({k: float(v) for k, v in weighted.items()}) if complete else None
    return {"candidate_publication_count": len(pubs),"publication_count": (sum(confirmed_raw.values()) if all(v == 0 for v in unresolved_eligibility.values()) else None),"confirmed_publication_count": sum(confirmed_raw.values()),"excluded_publication_count": excluded,"unresolved_eligibility_count": sum(unresolved_eligibility.values()),"raw": raw,"raw_confirmed": confirmed_raw,"unresolved_eligibility_by_bucket": unresolved_eligibility,"weighted": weighted,"weighted_known": {k: round(v, 10) for k, v in weighted_known.items()},"unresolved_weight_count": unresolved_weight,"over_10": over_10,"a_score": score}


def compare_to_ministry(publications: Iterable[CanonicalPublication], claim: MinistryClaim, rules: RuleEngine) -> list[dict[str, Any]]:
    calc = aggregate(publications, rules)
    rows = [("publication_count", claim.publication_count, calc["publication_count"]),("q1_raw", claim.q1_raw, calc["raw"]["a1"]),("q1_weighted", claim.q1_weighted, calc["weighted"]["a1"]),("q2_raw", claim.q2_raw, calc["raw"]["a2"]),("q2_weighted", claim.q2_weighted, calc["weighted"]["a2"]),("q3_raw", claim.q3_raw, calc["raw"]["a3"]),("q3_weighted", claim.q3_weighted, calc["weighted"]["a3"]),("a4_raw", claim.a4_raw, calc["raw"]["a4"]),("a4_weighted", claim.a4_weighted, calc["weighted"]["a4"]),("a_score", claim.a_score, calc["a_score"])]
    return [{"metric": name,"ministry_claim": ministry,"calculated": calculated,"difference": (calculated - ministry) if calculated is not None else None} for name, ministry, calculated in rows]
