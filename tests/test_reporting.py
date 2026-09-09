from monverify.models import CanonicalPublication
from monverify.omega import OMEGA_COLUMN_ORDER
from monverify.reporting import united_verification_dataframe


def test_united_table_preserves_omega_columns_and_sorts_resolved_then_source_title():
    unresolved = CanonicalPublication(
        canonical_id="u1",
        title="Unresolved title",
        source_title="Beta Journal",
        verification_status="manual_review",
        selected_institution_count=None,
        omega_authors="Omega Author",
        muv_authors_wos=["WoS Author, A."],
        omega_original={
            "Reference": "Original unresolved reference",
            "Journal": "Beta Journal",
            "publicationType": "Article",
            "Issue year": "2025",
            "DOI": "10.1000/u",
            "WoSId": "WOS:U",
            "ScopusId": "100",
            "JIFQuartile": "2",
            "Authors MU-Varna": "Omega Author",
            "Link WOS": "https://example.org/wos/u",
            "Link Scopus": "https://example.org/scopus/u",
        },
    )
    resolved_b = CanonicalPublication(
        canonical_id="c2",
        title="Resolved B",
        source_title="Gamma Journal",
        verification_status="confirmed",
        selected_institution_count=2,
        scopus_id="200",
        scopus_eid="2-s2.0-200",
        omega_original={
            "Reference": "Resolved B reference", "Journal": "Gamma Journal", "publicationType": "Article",
            "Issue year": "2025", "DOI": "10.1000/b", "WoSId": "WOS:B", "ScopusId": "old",
            "JIFQuartile": "1", "Authors MU-Varna": "B Author", "Link WOS": "", "Link Scopus": "",
        },
    )
    resolved_a = CanonicalPublication(
        canonical_id="c1",
        title="Resolved A",
        source_title="Alpha Journal",
        verification_status="confirmed",
        selected_institution_count=3,
        scopus_id="300",
        scopus_eid="2-s2.0-300",
        muv_authors_wos=["Confirmed, M."],
        omega_original={
            "Reference": "Resolved A reference", "Journal": "Alpha Journal", "publicationType": "Article",
            "Issue year": "2025", "DOI": "10.1000/a", "WoSId": "WOS:A", "ScopusId": "",
            "JIFQuartile": "1", "Authors MU-Varna": "Original MUV Author", "Link WOS": "", "Link Scopus": "",
        },
    )

    frame = united_verification_dataframe([unresolved, resolved_b, resolved_a])
    assert list(frame.columns[: len(OMEGA_COLUMN_ORDER)]) == OMEGA_COLUMN_ORDER
    assert list(frame["Review group"]) == ["Resolved", "Resolved", "Unresolved"]
    assert list(frame["Verified source title"]) == ["Alpha Journal", "Gamma Journal", "Beta Journal"]
    assert frame.iloc[0]["Authors MU-Varna"] == "Original MUV Author"
    assert frame.iloc[0]["MUV authors WOS"] == "Confirmed, M."
    assert frame.iloc[0]["ScopusId"] == "300"
    assert frame.iloc[0]["Scopus EID"] == "2-s2.0-300"
    assert frame.iloc[2]["Reference"] == "Original unresolved reference"


def test_removed_record_is_not_in_main_united_table():
    kept = CanonicalPublication(canonical_id="k", title="Keep", source_title="A", selected_institution_count=1)
    removed = CanonicalPublication(canonical_id="r", title="Remove", source_title="B", selected_institution_count=1, manually_removed=True)
    frame = united_verification_dataframe([kept, removed])
    assert list(frame["Canonical ID"]) == ["k"]
