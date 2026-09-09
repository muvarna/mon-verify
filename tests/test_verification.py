import pandas as pd
from monverify.incites import QuartileIndex
from monverify.models import SourceRecord
from monverify.rules import RuleEngine
from monverify.verification import merge_group

def test_wos_count_has_priority_over_scopus():
    q = QuartileIndex(pd.DataFrame([{"Name": "Journal", "ISSN": "1234-5678", "eISSN": "", "Journal Impact Factor": "5", "JIF Quartile": "Q1"}]))
    rules = RuleEngine.from_yaml("config/rules_2025.yaml")
    group = [SourceRecord(source="omega", source_id="o", title="T", normalized_title="t", year=2025, source_title="Journal", issn="12345678", omega_jif_quartile="Q1"),SourceRecord(source="wos", source_id="w", title="T", normalized_title="t", year=2025, source_title="Journal", issn="12345678", institution_count=11, muv_affiliation=True),SourceRecord(source="scopus", source_id="s", title="T", normalized_title="t", year=2025, source_title="Journal", issn="12345678", institution_count=9, muv_affiliation=True)]
    pub = merge_group(group, quartiles=q, rules=rules)
    assert pub.selected_institution_count == 11; assert pub.institution_count_source == "wos"; assert pub.over_10_institutions is True; assert pub.weighted_contribution == 0.1; assert "INSTITUTION_COUNT_MISMATCH" in pub.discrepancy_codes

def test_omega_only_is_not_treated_as_verified_eligible():
    q = QuartileIndex(pd.DataFrame([{"Name": "Journal", "ISSN": "1234-5678", "eISSN": "", "Journal Impact Factor": "5", "JIF Quartile": "Q1"}]))
    rules = RuleEngine.from_yaml("config/rules_2025.yaml")
    pub = merge_group([SourceRecord(source="omega", source_id="o", title="T", normalized_title="t", year=2025, source_title="Journal", issn="12345678")], quartiles=q, rules=rules)
    assert pub.eligible_for_calculation is None; assert pub.weighted_contribution is None; assert pub.verification_status == "manual_review"
