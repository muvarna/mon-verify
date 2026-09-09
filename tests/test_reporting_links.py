from monverify.models import CanonicalPublication
from monverify.reporting import united_verification_dataframe


def test_united_table_uses_verified_wos_and_canonical_scopus_eid_links():
    pub = CanonicalPublication(
        canonical_id="doi:10.1000/test",
        doi="10.1000/test",
        wos_ut="WOS:000123",
        scopus_id="123456789",
        scopus_eid="2-s2.0-123456789",
        title="Test title",
        source_title="Journal",
        selected_institution_count=2,
        in_omega=True,
        in_wos=True,
        in_scopus=True,
        omega_original={
            "Reference": "Original reference", "Journal": "Original journal", "publicationType": "article",
            "Issue year": "2025", "DOI": "10.1000/test", "WoSId": "WOS:000123", "ScopusId": "old",
            "JIFQuartile": "Q1", "Authors MU-Varna": "Author A", "Link WOS": "", "Link Scopus": "",
        },
        provenance=[{"source": "wos", "evidence_url": "https://www.webofscience.com/wos/woscc/full-record/WOS:000123"}],
    )
    row = united_verification_dataframe([pub]).iloc[0]
    assert row["Link WOS"] == "https://www.webofscience.com/wos/woscc/full-record/WOS:000123"
    assert row["Link Scopus"] == "https://www.scopus.com/record/display.uri?eid=2-s2.0-123456789&origin=resultslist"
    assert row["ScopusId"] == "123456789"
    assert row["Scopus EID"] == "2-s2.0-123456789"


def test_united_table_keeps_original_link_for_rc_identifier():
    pub = CanonicalPublication(
        canonical_id="omega:1",
        wos_ut="RC:000123",
        title="Research Commons candidate",
        source_title="Journal",
        selected_institution_count=None,
        in_omega=True,
        in_wos=False,
        omega_original={
            "Reference": "Original reference", "Journal": "Original journal", "publicationType": "article",
            "Issue year": "2025", "DOI": "", "WoSId": "RC:000123", "ScopusId": "",
            "JIFQuartile": "", "Authors MU-Varna": "Author A", "Link WOS": "original-omega-link", "Link Scopus": "",
        },
    )
    frame = united_verification_dataframe([pub])
    assert frame.iloc[0]["Link WOS"] == "original-omega-link"
