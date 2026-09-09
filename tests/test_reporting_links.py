from monverify.models import CanonicalPublication
from monverify.reporting import united_verification_dataframe


def test_united_table_prefers_verified_source_links():
    pub = CanonicalPublication(
        canonical_id="doi:10.1000/test",
        doi="10.1000/test",
        wos_ut="WOS:000123",
        scopus_id="123456789",
        scopus_eid="2-s2.0-123456789",
        title="Test title",
        in_omega=True,
        in_wos=True,
        in_scopus=True,
        omega_original={
            "Reference": "Original reference",
            "Journal": "Original journal",
            "publicationType": "article",
            "Issue year": "2025",
            "DOI": "10.1000/test",
            "WoSId": "WOS:000123",
            "ScopusId": "123456789",
            "JIFQuartile": "Q1",
            "Authors MU-Varna": "Author A",
            "Link WOS": "",
            "Link Scopus": "",
        },
        provenance=[
            {
                "source": "wos",
                "evidence_url": "https://www.webofscience.com/wos/woscc/full-record/WOS:000123",
            },
            {
                "source": "scopus",
                "evidence_url": "https://www.scopus.com/inward/record.uri?scp=123456789&origin=inward",
            },
        ],
    )
    frame = united_verification_dataframe([pub])
    row = frame.iloc[0]
    assert row["Link WOS"] == "https://www.webofscience.com/wos/woscc/full-record/WOS:000123"
    assert row["Link Scopus"] == "https://www.scopus.com/inward/record.uri?scp=123456789&origin=inward"


def test_united_table_keeps_original_link_when_source_not_verified_and_does_not_generate_rc_link():
    pub = CanonicalPublication(
        canonical_id="omega:1",
        wos_ut="RC:000123",
        title="Research Commons candidate",
        in_omega=True,
        in_wos=False,
        omega_original={
            "Reference": "Original reference",
            "Journal": "Original journal",
            "publicationType": "article",
            "Issue year": "2025",
            "DOI": "",
            "WoSId": "RC:000123",
            "ScopusId": "",
            "JIFQuartile": "",
            "Authors MU-Varna": "Author A",
            "Link WOS": "original-omega-link",
            "Link Scopus": "",
        },
    )
    frame = united_verification_dataframe([pub])
    assert frame.iloc[0]["Link WOS"] == "original-omega-link"
