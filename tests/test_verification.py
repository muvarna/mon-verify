import pandas as pd

from monverify.incites import QuartileIndex
from monverify.manual import apply_manual_overrides
from monverify.models import CanonicalPublication, SourceRecord
from monverify.rules import RuleEngine
from monverify.scival import SciValIndex, SciValPublication
from monverify.verification import aggregate, merge_group


def _quartiles():
    return QuartileIndex(pd.DataFrame([
        {"Name": "Journal", "ISSN": "1234-5678", "eISSN": "", "Journal Impact Factor": "5", "JIF Quartile": "Q1"}
    ]))


def _scival(count=9, sid="123456789", doi="10.1000/x", year=2025):
    return SciValIndex([
        SciValPublication(
            eid=f"2-s2.0-{sid}",
            scopus_id=sid,
            doi=doi,
            title="T",
            normalized_title="t",
            year=year,
            institution_count=count,
        )
    ])


def test_wos_count_has_priority_over_scival_and_boundary_mismatch_is_flagged():
    rules = RuleEngine.from_yaml("config/rules_2025.yaml")
    group = [
        SourceRecord(source="omega", source_id="o", title="T", normalized_title="t", year=2025, source_title="Journal", issn="12345678", doi="10.1000/x"),
        SourceRecord(source="wos", source_id="w", wos_ut="WOS:1", title="T", normalized_title="t", year=2025, source_title="Journal", issn="12345678", doi="10.1000/x", institution_count=11, muv_affiliation=True),
    ]
    pub = merge_group(group, quartiles=_quartiles(), rules=rules, scival_index=_scival(9))
    assert pub.selected_institution_count == 11
    assert pub.institution_count_source == "wos"
    assert pub.over_10_institutions is True
    assert pub.weighted_contribution == 0.1
    assert "INSTITUTION_COUNT_MISMATCH" in pub.discrepancy_codes


def test_institution_count_mismatch_below_threshold_is_ignored():
    rules = RuleEngine.from_yaml("config/rules_2025.yaml")
    group = [
        SourceRecord(source="omega", source_id="o", title="T", normalized_title="t", year=2025, source_title="Journal", issn="12345678", doi="10.1000/x"),
        SourceRecord(source="wos", source_id="w", wos_ut="WOS:1", title="T", normalized_title="t", year=2025, source_title="Journal", issn="12345678", doi="10.1000/x", institution_count=8, muv_affiliation=True),
    ]
    pub = merge_group(group, quartiles=_quartiles(), rules=rules, scival_index=_scival(10))
    assert pub.selected_institution_count == 8
    assert pub.weighted_contribution == 1.0
    assert "INSTITUTION_COUNT_MISMATCH" not in pub.discrepancy_codes


def test_year_mismatch_is_ignored_when_any_source_is_assessment_year():
    rules = RuleEngine.from_yaml("config/rules_2025.yaml")
    group = [
        SourceRecord(source="omega", source_id="o", title="T", normalized_title="t", year=2024, source_title="Journal", issn="12345678", doi="10.1000/x"),
        SourceRecord(source="wos", source_id="w", wos_ut="WOS:1", title="T", normalized_title="t", year=2025, source_title="Journal", issn="12345678", doi="10.1000/x", institution_count=4, muv_affiliation=True),
    ]
    pub = merge_group(group, quartiles=_quartiles(), rules=rules, scival_index=_scival(4, year=2024))
    assert "YEAR_MISMATCH" not in pub.discrepancy_codes


def test_year_mismatch_is_flagged_when_sources_disagree_and_none_is_assessment_year():
    rules = RuleEngine.from_yaml("config/rules_2025.yaml")
    group = [
        SourceRecord(source="omega", source_id="o", title="T", normalized_title="t", year=2024, source_title="Journal", issn="12345678", doi="10.1000/x"),
        SourceRecord(source="wos", source_id="w", wos_ut="WOS:1", title="T", normalized_title="t", year=2023, source_title="Journal", issn="12345678", doi="10.1000/x", institution_count=4, muv_affiliation=True),
    ]
    pub = merge_group(group, quartiles=_quartiles(), rules=rules, scival_index=_scival(4, year=2024))
    assert "YEAR_MISMATCH" in pub.discrepancy_codes


def test_scival_is_used_when_wos_count_missing_and_eid_is_added():
    rules = RuleEngine.from_yaml("config/rules_2025.yaml")
    group = [
        SourceRecord(source="omega", source_id="o", title="T", normalized_title="t", year=2025, source_title="Journal", issn="12345678", doi="10.1000/x"),
        SourceRecord(source="wos", source_id="w", wos_ut="WOS:1", title="T", normalized_title="t", year=2025, source_title="Journal", issn="12345678", doi="10.1000/x", institution_count=None, muv_affiliation=True),
    ]
    pub = merge_group(group, quartiles=_quartiles(), rules=rules, scival_index=_scival(9))
    assert pub.selected_institution_count == 9
    assert pub.institution_count_source == "scival"
    assert pub.scopus_id == "123456789"
    assert pub.scopus_eid == "2-s2.0-123456789"
    assert pub.eligible_for_calculation is True
    assert pub.weighted_contribution == 1.0


def test_scival_doi_corrects_wrong_omega_scopus_id():
    rules = RuleEngine.from_yaml("config/rules_2025.yaml")
    group = [
        SourceRecord(source="omega", source_id="o", scopus_id="999999", title="T", normalized_title="t", year=2025, source_title="Journal", issn="12345678", doi="10.1000/x"),
    ]
    pub = merge_group(group, quartiles=_quartiles(), rules=rules, scival_index=_scival(9, sid="123456789"))
    assert pub.original_omega_scopus_id == "999999"
    assert pub.scopus_id == "123456789"
    assert pub.scopus_eid == "2-s2.0-123456789"
    assert "SCOPUS_ID_CORRECTED_FROM_SCIVAL" in pub.discrepancy_codes


def test_zero_or_missing_institution_count_is_unresolved_even_with_identifier():
    rules = RuleEngine.from_yaml("config/rules_2025.yaml")
    group = [SourceRecord(source="omega", source_id="o", wos_ut="WOS:1", title="T", normalized_title="t", year=2025, source_title="Journal", issn="12345678")]
    pub = merge_group(group, quartiles=_quartiles(), rules=rules)
    assert pub.selected_institution_count is None
    assert pub.eligible_for_calculation is None
    assert pub.verification_status == "manual_review"
    assert "MISSING_INSTITUTION_COUNT" in pub.discrepancy_codes


def _pub(cid: str, bucket: str, count, weight, removed=False):
    return CanonicalPublication(
        canonical_id=cid,
        ministry_bucket=bucket,
        selected_institution_count=count,
        eligible_for_calculation=True if count else None,
        weighted_contribution=weight,
        contribution_multiplier=weight,
        over_10_institutions=(weight == 0.1),
        manually_removed=removed,
    )


def test_aggregate_keeps_numeric_resolved_subtotals_with_unresolved_records():
    rules = RuleEngine.from_yaml("config/rules_2025.yaml")
    pubs = [
        _pub("q1-confirmed", "a1", 5, 1.0),
        _pub("q1-unresolved", "a1", None, None),
        _pub("q2-confirmed", "a2", 11, 0.1),
        _pub("q3-confirmed", "a3", 3, 1.0),
        _pub("a4-removed", "a4", 2, 1.0, removed=True),
    ]
    result = aggregate(pubs, rules)
    assert result["publication_count"] == 3
    assert result["raw"] == {"a1": 1, "a2": 1, "a3": 1, "a4": 0}
    assert result["weighted"] == {"a1": 1.0, "a2": 0.1, "a3": 1.0, "a4": 0.0}
    assert result["unresolved_institution_count"] == 1
    assert result["removed_publication_count"] == 1
    assert result["calculation_complete"] is False
    assert result["a_score"] == 7.3


def test_manual_count_resolves_record_and_manual_remove_excludes_record():
    rules = RuleEngine.from_yaml("config/rules_2025.yaml")
    unresolved = CanonicalPublication(canonical_id="u", wos_ut="WOS:1", ministry_bucket="a1")
    removed = CanonicalPublication(canonical_id="r", scopus_id="123", ministry_bucket="a2", selected_institution_count=4, weighted_contribution=1.0)
    pubs = apply_manual_overrides(
        [unresolved, removed],
        rules,
        {
            "u": {"manual_institution_count": 11, "remove": False, "note": "checked manually"},
            "r": {"manual_institution_count": None, "remove": True, "note": "not eligible"},
        },
    )
    assert pubs[0].selected_institution_count == 11
    assert pubs[0].institution_count_source == "manual"
    assert pubs[0].weighted_contribution == 0.1
    assert pubs[0].verification_status == "confirmed"
    assert pubs[1].manually_removed is True
    assert pubs[1].verification_status == "removed"
