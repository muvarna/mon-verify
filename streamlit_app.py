from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import streamlit as st

from monverify.clients.common import APIRequestError
from monverify.clients.scopus import ScopusClient, scopus_entries_from_payload
from monverify.clients.wos import WOSClient, wos_records_from_payload
from monverify.ministry import parse_ministry_workbook
from monverify.omega import omega_records
from monverify.reporting import publications_dataframe
from monverify.rules import RuleEngine
from monverify.verification import aggregate, build_canonical_publications, compare_to_ministry

st.set_page_config(page_title="MON Verify — MU-Varna", layout="wide")
st.title("MON Verify — MU-Varna 2025")
st.caption("Independent, publication-level verification of MON bibliometric claims.")

RULES_PATH = Path("config/rules_2025.yaml")
RULES = RuleEngine.from_yaml(RULES_PATH)
WOS_DATABASE_ID = str(RULES.rules.get("wos", {}).get("database_id", "WOK"))


def _save_upload(upload, folder: Path, prefix: str = "") -> Path | None:
    if upload is None:
        return None
    path = folder / f"{prefix}{upload.name}"
    path.write_bytes(upload.getvalue())
    return path


def _save_uploads(uploads, folder: Path, prefix: str) -> list[Path]:
    return [_save_upload(upload, folder, f"{prefix}{i}_") for i, upload in enumerate(uploads or [], start=1)]


def _secret(name: str) -> str:
    try:
        return str(st.secrets.get(name, "")).strip()
    except Exception:
        return os.getenv(name, "").strip()


def _api_error_text(service: str, exc: APIRequestError) -> str:
    status = exc.status_code
    if service == "Scopus" and status == 401:
        message = (
            "Scopus rejected the request with HTTP 401 Unauthorized. The API key may be invalid, "
            "or the request may lack the institutional entitlement required from Streamlit Cloud."
        )
    elif service == "Scopus" and status == 403:
        message = "Scopus authenticated the request but denied access (HTTP 403). Check API entitlements/Insttoken."
    elif status in {401, 403}:
        message = f"{service} authentication/authorization failed (HTTP {status}). Check the configured API credentials and entitlement."
    elif status == 429:
        message = f"{service} rate limit reached (HTTP 429). Try again later or use cached/uploaded API evidence."
    elif status:
        message = f"{service} API returned HTTP {status}."
    else:
        message = f"{service} API request failed."
    if exc.detail:
        message += f" Server message: {exc.detail}"
    return message


def _show_api_failure(service: str, exc: Exception) -> None:
    if isinstance(exc, APIRequestError):
        st.error(_api_error_text(service, exc))
        if service == "Scopus" and exc.status_code in {401, 403}:
            st.info(
                "Streamlit Community Cloud runs outside the MU-Varna institutional IP range. "
                "If your Scopus access depends on institutional IP authentication, configure an Elsevier "
                "institution token (`SCOPUS_INSTTOKEN`) in Streamlit Secrets, or retrieve Scopus data locally "
                "and use Uploaded/cached data mode."
            )
    else:
        st.error(f"{service} retrieval failed: {exc}")


with st.sidebar:
    st.header("Mode")
    mode = st.radio("Data source", ["Uploaded/cached data", "Live APIs"])
    st.markdown("**Institution identifiers**")
    st.code(f"WoS: Medical University Varna\nWoS database: {WOS_DATABASE_ID}\nScopus AF-ID: 60005828")

st.subheader("Input files")
col1, col2, col3 = st.columns(3)
with col1:
    ministry_upload = st.file_uploader("Ministry XLSX", type=["xlsx"])
with col2:
    omega_upload = st.file_uploader("OMEGA CSV", type=["csv"])
with col3:
    quartile_upload = st.file_uploader("2025 JCR/InCites quartiles CSV", type=["csv"])

wos_uploads: list = []
scopus_uploads: list = []

if mode == "Uploaded/cached data":
    col4, col5 = st.columns(2)
    with col4:
        wos_uploads = st.file_uploader(
            "Optional WoS JSON files",
            type=["json"],
            accept_multiple_files=True,
            help="You can upload both institution-discovery and OMEGA-ID verification JSON files.",
        )
    with col5:
        scopus_uploads = st.file_uploader(
            "Optional Scopus JSON files",
            type=["json"],
            accept_multiple_files=True,
            help="You can upload both institution-discovery and OMEGA-ID verification JSON files.",
        )
else:
    st.subheader("Live API retrieval")
    workflows = st.multiselect(
        "Retrieval workflows",
        ["Independent institutional discovery", "Verify OMEGA identifiers"],
        default=["Independent institutional discovery", "Verify OMEGA identifiers"],
    )
    wos_key = st.text_input("WoS Expanded API key", value=_secret("WOS_API_KEY"), type="password").strip()
    scopus_key = st.text_input("Scopus API key", value=_secret("SCOPUS_API_KEY"), type="password").strip()
    scopus_insttoken = st.text_input(
        "Optional Scopus institution token", value=_secret("SCOPUS_INSTTOKEN"), type="password"
    ).strip()
    year = st.number_input("Year", min_value=2000, max_value=2100, value=2025, step=1)

    st.caption(
        "Configured credentials — "
        f"WoS API key: {'yes' if wos_key else 'no'} · "
        f"Scopus API key: {'yes' if scopus_key else 'no'} · "
        f"Scopus Insttoken: {'yes' if scopus_insttoken else 'no'}"
    )

    if st.button("Fetch API evidence", type="primary"):
        if not wos_key and not scopus_key:
            st.error("Enter at least one API key.")
        elif "Verify OMEGA identifiers" in workflows and omega_upload is None:
            st.error("OMEGA CSV is required for OMEGA-identifier verification.")
        else:
            st.session_state["wos_live_files"] = []
            st.session_state["scopus_live_files"] = []
            st.session_state["api_errors"] = []
            omega_source_records = []

            if "Verify OMEGA identifiers" in workflows and omega_upload is not None:
                with tempfile.TemporaryDirectory() as tmp:
                    omega_path = Path(tmp) / omega_upload.name
                    omega_path.write_bytes(omega_upload.getvalue())
                    omega_source_records = omega_records(omega_path)

            if wos_key:
                try:
                    client = WOSClient(wos_key)
                    if "Independent institutional discovery" in workflows:
                        with st.spinner("WoS: independent institutional discovery..."):
                            query = f'OG=("Medical University Varna") AND PY={int(year)}'
                            pages = client.search_pages(query, database_id=WOS_DATABASE_ID)
                            wrapper = {
                                "mode": "institution_discovery",
                                "query": query,
                                "database_id": WOS_DATABASE_ID,
                                "retrieved_at": datetime.now(timezone.utc).isoformat(),
                                "pages": pages,
                            }
                            st.session_state["wos_live_files"].append(wrapper)
                            st.success(
                                f"WoS discovery: {sum(len(wos_records_from_payload(p)) for p in pages)} record(s)."
                            )
                    if "Verify OMEGA identifiers" in workflows:
                        with st.spinner("WoS: verifying OMEGA identifiers..."):
                            ids = sorted({r.wos_ut for r in omega_source_records if r.wos_ut})
                            pages = client.get_by_ids(ids, database_id=WOS_DATABASE_ID)
                            st.session_state["wos_live_files"].append(
                                {
                                    "mode": "omega_ids",
                                    "database_id": WOS_DATABASE_ID,
                                    "requested_ids": ids,
                                    "retrieved_at": datetime.now(timezone.utc).isoformat(),
                                    "pages": pages,
                                }
                            )
                            st.success(f"WoS OMEGA-ID verification requested {len(ids)} identifier(s).")
                except Exception as exc:
                    st.session_state["api_errors"].append({"service": "WoS", "error": str(exc)})
                    _show_api_failure("WoS", exc)

            if scopus_key:
                try:
                    client = ScopusClient(scopus_key, insttoken=scopus_insttoken or None)
                    if "Independent institutional discovery" in workflows:
                        with st.spinner("Scopus: independent institutional discovery..."):
                            query = f"AF-ID(60005828) AND PUBYEAR = {int(year)}"
                            pages = client.search_pages(query)
                            st.session_state["scopus_live_files"].append(
                                {
                                    "mode": "institution_discovery",
                                    "query": query,
                                    "retrieved_at": datetime.now(timezone.utc).isoformat(),
                                    "pages": pages,
                                }
                            )
                            st.success(
                                f"Scopus discovery: {sum(len(scopus_entries_from_payload(p)) for p in pages)} record(s)."
                            )
                    if "Verify OMEGA identifiers" in workflows:
                        with st.spinner("Scopus: verifying OMEGA identifiers..."):
                            ids = sorted({r.scopus_id for r in omega_source_records if r.scopus_id})
                            abstracts = client.retrieve_many(ids)
                            st.session_state["scopus_live_files"].append(
                                {
                                    "mode": "omega_ids",
                                    "requested_ids": ids,
                                    "retrieved_at": datetime.now(timezone.utc).isoformat(),
                                    "abstracts": abstracts,
                                }
                            )
                            failures = sum(1 for x in abstracts if x.get("_monverify_error"))
                            st.success(
                                f"Scopus OMEGA-ID verification requested {len(ids)} identifier(s); failures: {failures}."
                            )
                except Exception as exc:
                    st.session_state["api_errors"].append({"service": "Scopus", "error": str(exc)})
                    _show_api_failure("Scopus", exc)

            available = len(st.session_state.get("wos_live_files", [])) + len(
                st.session_state.get("scopus_live_files", [])
            )
            if available:
                st.success(f"API retrieval completed with {available} cached evidence set(s). You can run verification now.")
            elif st.session_state.get("api_errors"):
                st.warning("No live API evidence was retrieved. You can still switch to Uploaded/cached data mode.")

if st.button("Run verification", disabled=not (ministry_upload and omega_upload and quartile_upload)):
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp)
        ministry_path = _save_upload(ministry_upload, folder)
        omega_path = _save_upload(omega_upload, folder)
        quartile_path = _save_upload(quartile_upload, folder)
        wos_paths: list[Path] = []
        scopus_paths: list[Path] = []
        if mode == "Uploaded/cached data":
            wos_paths = [x for x in _save_uploads(wos_uploads, folder, "wos_") if x]
            scopus_paths = [x for x in _save_uploads(scopus_uploads, folder, "scopus_") if x]
        else:
            for i, payload in enumerate(st.session_state.get("wos_live_files", []), start=1):
                path = folder / f"wos_live_{i}.json"
                path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
                wos_paths.append(path)
            for i, payload in enumerate(st.session_state.get("scopus_live_files", []), start=1):
                path = folder / f"scopus_live_{i}.json"
                path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
                scopus_paths.append(path)

        claim = parse_ministry_workbook(ministry_path)
        pubs = build_canonical_publications(
            omega_path=omega_path,
            quartiles_path=quartile_path,
            rules_path=RULES_PATH,
            wos_json=wos_paths,
            scopus_json=scopus_paths,
        )
        st.session_state["claim"] = claim.model_dump()
        st.session_state["pubs"] = [p.model_dump() for p in pubs]
        st.session_state["comparison"] = compare_to_ministry(pubs, claim, RULES)
        st.session_state["aggregate"] = aggregate(pubs, RULES)

if "pubs" in st.session_state:
    from monverify.models import CanonicalPublication, MinistryClaim

    pubs = [CanonicalPublication(**x) for x in st.session_state["pubs"]]
    claim = MinistryClaim(**st.session_state["claim"])
    agg = st.session_state["aggregate"]
    comparison = pd.DataFrame(st.session_state["comparison"])
    frame = publications_dataframe(pubs)

    st.subheader("MON vs calculated")
    c1, c2, c3, c4 = st.columns(4)
    pub_count = agg["publication_count"]
    c1.metric(
        "Publications",
        pub_count if pub_count is not None else "unresolved",
        (pub_count - claim.publication_count if pub_count is not None else None),
    )
    q1w = agg["weighted"]["a1"]
    q2w = agg["weighted"]["a2"]
    score = agg["a_score"]
    c2.metric(
        "Q1 weighted",
        q1w if q1w is not None else "unresolved",
        (round(q1w - claim.q1_weighted, 3) if q1w is not None else None),
    )
    c3.metric(
        "Q2 weighted",
        q2w if q2w is not None else "unresolved",
        (round(q2w - claim.q2_weighted, 3) if q2w is not None else None),
    )
    c4.metric(
        "a score",
        score if score is not None else "unresolved",
        (round(score - claim.a_score, 3) if score is not None else None),
    )
    st.caption(
        f"Candidates: {agg['candidate_publication_count']} · confirmed eligible: {agg['confirmed_publication_count']} · "
        f"excluded: {agg['excluded_publication_count']} · unresolved eligibility: {agg['unresolved_eligibility_count']}"
    )
    st.dataframe(comparison, use_container_width=True, hide_index=True)

    tabs = st.tabs(["Publications", "Discrepancies", ">10 institutions", "Unresolved", "Downloads"])
    with tabs[0]:
        st.dataframe(frame, use_container_width=True, hide_index=True)
    with tabs[1]:
        discrepancies = frame[frame["discrepancy_codes"].fillna("").str.len() > 0]
        st.dataframe(discrepancies, use_container_width=True, hide_index=True)
    with tabs[2]:
        over_10 = frame[frame["over_10_institutions"] == True]
        st.dataframe(over_10, use_container_width=True, hide_index=True)
    with tabs[3]:
        unresolved = frame[frame["verification_status"] == "manual_review"]
        st.dataframe(unresolved, use_container_width=True, hide_index=True)
    with tabs[4]:
        st.download_button(
            "canonical_publications.csv",
            frame.to_csv(index=False).encode("utf-8-sig"),
            "canonical_publications.csv",
            "text/csv",
        )
        st.download_button(
            "ministry_comparison.csv",
            comparison.to_csv(index=False).encode("utf-8-sig"),
            "ministry_comparison.csv",
            "text/csv",
        )
        st.download_button(
            "ministry_corrections.csv",
            discrepancies.to_csv(index=False).encode("utf-8-sig"),
            "ministry_corrections.csv",
            "text/csv",
        )
        st.download_button(
            "unresolved_records.csv",
            unresolved.to_csv(index=False).encode("utf-8-sig"),
            "unresolved_records.csv",
            "text/csv",
        )
        st.download_button(
            "over_10_institutions.csv",
            over_10.to_csv(index=False).encode("utf-8-sig"),
            "over_10_institutions.csv",
            "text/csv",
        )
        summary = {"ministry_claim": claim.model_dump(), "calculated": agg}
        st.download_button(
            "verification_summary.json",
            json.dumps(summary, ensure_ascii=False, indent=2).encode("utf-8"),
            "verification_summary.json",
            "application/json",
        )
else:
    st.info("Upload the three required files, optionally retrieve/upload API evidence, then run verification.")
