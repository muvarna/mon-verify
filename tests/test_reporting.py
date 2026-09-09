from monverify.models import CanonicalPublication
from monverify.omega import OMEGA_COLUMN_ORDER
from monverify.reporting import united_verification_dataframe


def test_united_table_preserves_omega_columns_authors_and_order():
    unresolved = CanonicalPublication(
        canonical_id="u1",
        title="Unresolved title",
        verification_status="manual_review",
        eligible_for_calculation=None,
        omega_authors="Omega Author",
        muv_authors_wos=["WoS Author, A."],
        omega_original={
            "Reference": "Original unresolved reference",
            "Journal": "Journal U",
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
    confirmed = CanonicalPublication(
        canonical_id="c1",
        title="Confirmed title",
        verification_status="confirmed",
        eligible_for_calculation=True,
        muv_authors_wos=["Confirmed, M."],
        omega_original={
            "Reference": "Original confirmed reference",
            "Journal": "Journal C",
            "publicationType": "Article",
            "Issue year": "2025",
            "DOI": "10.1000/c",
            "WoSId": "WOS:C",
            "ScopusId": "200",
            "JIFQuartile": "1",
            "Authors MU-Varna": "Original MUV Author",
            "Link WOS": "https://example.org/wos/c",
            "Link Scopus": "https://example.org/scopus/c",
        },
    )

    frame = united_verification_dataframe([unresolved, confirmed])
    assert list(frame.columns[: len(OMEGA_COLUMN_ORDER)]) == OMEGA_COLUMN_ORDER
    assert frame.iloc[0]["Review group"] == "Confirmed"
    assert frame.iloc[1]["Review group"] == "Unresolved"
    assert frame.iloc[0]["Authors MU-Varna"] == "Original MUV Author"
    assert frame.iloc[0]["MUV authors WOS"] == "Confirmed, M."
    assert frame.iloc[1]["Reference"] == "Original unresolved reference"
