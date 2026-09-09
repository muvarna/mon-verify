import pandas as pd

from monverify.incites import QuartileIndex
from monverify.models import CanonicalPublication, SourceRecord
from monverify.rules import RuleEngine
from monverify.verification import aggregate, merge_group


def _quartiles():
    return QuartileIndex(pd.DataFrame([
        {"Name": "Journal", "ISSN": "1234-5678", "eISSN": "", "Journal Impact Factor": "5", "JIF Quartile": "Q1"}
    ]))


def test_wos_count_has_priority_over_scival():
    rules = RuleEngine.from_yaml("config/rules_2025.yaml")
    group = [
        SourceRecord(source="omega", source_id="o", title="T", normalized_title="t", year=2025, source_title="Journal", issn="12345678", doi="10.1/x"),
        SourceRecord(source="wos", source_id="w", title="T", normalized_title="t", year=2025, source_title="Journal", issn="12345678", doi="10.1/x", institution_count=11, muv_affiliation=True),
    ]
    pub = merge_group(group, quartiles=_quartiles(), rules=rules, scival_lookup={("doi", "10.1/x"): 9})
    assert pub.selected_institution_count == 11
    assert pub.institution_count_source == "wos"
    assert pub.over_10_institutions is True
    assert pub.weighted_contribution == 0.1
    assert "INSTITUTION_COUNT_MISMATCH" in pub.discrepancy_codes


def test_scival_is_used_when_wos_count_missing():
    rules = RuleEngine.from_yaml("config/rules_2025.yaml")
    group = [
        SourceRecord(source="omega", source_id="o", title="T", normalized_title="t", year=2025, source_title="Journal", issn="12345678", doi="10.1/x"),
        SourceRecord(source="wos", source_id="w", title="T", normalized_title="t", year=2025, source_title="Journal", issn="12345678", doi="10.1/x", institution_count=None, muv_affiliation=True),
    ]
    pub = merge_group(group, quartiles=_quartiles(), rules=rules, scival_lookup={("doi", "10.1/x"): 9})
    assert pub.selected_institution_count == 9
    assert pub.institution_count_source == "scival"
    assert pub.weighted_contribution == 1.0


def test_omega_only_is_not_treated_as_verified_eligible():
    rules = RuleEngine.from_yaml("config/rules_2025.yaml")
    pub = merge_group(
        [SourceRecord(source="omega", source_id="o", title="T", normalized_title="t", year=2025, source_title="Journal", issn="12345678")],
        quartiles=_quartiles(),
        rules=rules,
    )
    assert pub.eligible_for_calculation is None
    assert pub.weighted_contribution is None
    assert pub.verification_status == "manual_review"


def _pub(cid: str, bucket: str, eligible, weight):
    return CanonicalPublication(
        canonical_id=cid,
        ministry_bucket=bucket,
        eligible_for_calculation=eligible,
        weighted_contribution=weight,
        contribution_multiplier=weight,
        over_10_institutions=(weight == 0.1),
    )


def test_aggregate_keeps_numeric_confirmed_subtotals_with_unresolved_records():
    rules = RuleEngine.from_yaml("config/rules_2025.yaml")
    pubs = [
        _pub("q1-confirmed", "a1", True, 1.0),
        _pub("q1-unresolved", "a1", None, None),
        _pub("q2-confirmed", "a2", True, 0.1),
        _pub("q3-confirmed", "a3", True, 1.0),
        _pub("a4-excluded", "a4", False, None),
    ]
    result = aggregate(pubs, rules)
    assert result["publication_count"] == 3
    assert result["raw"] == {"a1": 1, "a2": 1, "a3": 1, "a4": 0}
    assert result["weighted"] == {"a1": 1.0, "a2": 0.1, "a3": 1.0, "a4": 0.0}
    assert result["unresolved_eligibility_count"] == 1
    assert result["calculation_complete"] is False
    assert result["a_score"] == 7.3
