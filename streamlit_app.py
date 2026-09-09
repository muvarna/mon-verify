from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import streamlit as st

from monverify.clients.common import APIRequestError
from monverify.clients.wos import WOSClient, compact_wos_pages, is_research_commons_uid
from monverify.manual import apply_manual_overrides, load_manual_overrides
from monverify.ministry import parse_ministry_workbook
from monverify.models import CanonicalPublication, MinistryClaim
from monverify.omega import omega_records
from monverify.reporting import publications_dataframe, united_verification_dataframe
from monverify.rules import RuleEngine
from monverify.scival import inspect_scival
from monverify.verification import aggregate, build_canonical_publications, compare_to_ministry

st.set_page_config(page_title="MON Verify — MU-Varna", layout="wide")
st.title("MON Verify — MU-Varna 2025")
st.caption("Web of Science Expanded + OMEGA + JCR/InCites quartiles + SciVal. Scopus API is not used.")

RULES_PATH = Path("config/rules_2025.yaml")
RULES = RuleEngine.from_yaml(RULES_PATH)
WOS_DATABASE_ID = str(RULES.rules.get("wos", {}).get("database_id", "WOK"))
WOS_ORG = str(RULES.rules.get("wos", {}).get("organization_enhanced", "Medical University Varna"))


def _save_upload(upload, folder: Path, prefix: str = "") -> Path | None:
    if upload is None:
        return None
    path = folder / f"{prefix}{upload.name}"
    path.write_bytes(upload.getvalue())
    return path


def _save_uploads(uploads, folder: Path, prefix: str) -> list[Path]:
    return [p for p in (_save_upload(u, folder, f"{prefix}{i}_") for i, u in enumerate(uploads or [], 1)) if p]


def _secret(name: str) -> str:
    try:
        return str(st.secrets.get(name, "")).strip()
    except Exception:
        return os.getenv(name, "").strip()


def _api_error_text(exc: Exception) -> str:
    if isinstance(exc, APIRequestError):
        if exc.status_code in {401, 403}:
            return f"WoS authentication/authorization failed (HTTP {exc.status_code}). {exc.detail or ''}".strip()
        if exc.status_code == 429:
            return "WoS rate limit reached (HTTP 429)."
        return f"WoS API request failed{f' (HTTP {exc.status_code})' if exc.status_code else ''}. {exc.detail or ''}".strip()
    return f"WoS retrieval failed: {exc}"


def _recalculate(pubs: list[CanonicalPublication], claim: MinistryClaim) -> None:
    st.session_state["pubs"] = [p.model_dump() for p in pubs]
    st.session_state["aggregate"] = aggregate(pubs, RULES)
    st.session_state["comparison"] = compare_to_ministry(pubs, claim, RULES)


with st.sidebar:
    st.header("Workflow")
    mode = st.radio("WoS evidence source", ["Uploaded/cached JSON", "Live WoS API"])
    st.code(f"WoS organization: {WOS_ORG}\nWoS database: {WOS_DATABASE_ID}")
    st.caption("RC-prefix records are excluded. Institution-count priority: manual override → WoS → SciVal.")

st.subheader("Required inputs")
col1, col2, col3 = st.columns(3)
with col1:
    omega_upload = st.file_uploader("OMEGA CSV", type=["csv"])
with col2:
    quartile_upload = st.file_uploader("2025 JCR/InCites quartiles CSV", type=["csv"])
with col3:
    scival_upload = st.file_uploader("SciVal CSV", type=["csv"], help="Header-first CSV with EID and Number of Institutions.")

manual_upload = st.file_uploader(
    "Optional manual_overrides.csv",
    type=["csv"],
    help="Reuse prior manual institution counts/removals. Columns: canonical_id, manual_institution_count, remove, note.",
)
ministry_upload = st.file_uploader("Optional Ministry XLSX", type=["xlsx"])

if scival_upload is not None:
    try:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / scival_upload.name
            p.write_bytes(scival_upload.getvalue())
            info = inspect_scival(p)
        st.success(
            f"SciVal: {info['rows']} rows · {info['zero_or_missing_institutions']} zero/missing institution counts · "
            f"{info['over_10_institutions']} with >10 institutions."
        )
    except Exception as exc:
        st.error(f"SciVal file could not be read: {exc}")

wos_uploads: list = []
if mode == "Uploaded/cached JSON":
    wos_uploads = st.file_uploader("WoS compact/raw JSON files", type=["json"], accept_multiple_files=True)
else:
    st.subheader("Live Web of Science retrieval")
    workflows = st.multiselect(
        "Retrieval workflows",
        ["Independent institutional discovery", "Verify OMEGA identifiers"],
        default=["Independent institutional discovery", "Verify OMEGA identifiers"],
    )
    wos_key = st.text_input("WoS Expanded API key", value=_secret("WOS_API_KEY"), type="password").strip()
    year = st.number_input("Year", min_value=2000, max_value=2100, value=2025, step=1)
    if st.button("Fetch WoS evidence", type="primary"):
        if not wos_key:
            st.error("Enter WOS_API_KEY.")
        elif "Verify OMEGA identifiers" in workflows and omega_upload is None:
            st.error("OMEGA CSV is required for OMEGA-ID verification.")
        else:
            st.session_state["wos_live_payloads"] = []
            try:
                client = WOSClient(wos_key)
                if "Independent institutional discovery" in workflows:
                    query = f'OG=("{WOS_ORG}") AND PY={int(year)}'
                    with st.spinner("WoS institutional discovery..."):
                        pages = client.search_pages(query, database_id=WOS_DATABASE_ID, use_cache=False)
                    records = compact_wos_pages(pages, organization=WOS_ORG)
                    st.session_state["wos_live_payloads"].append({
                        "format": "monverify-wos-compact-v1", "mode": "institution_discovery", "query": query,
                        "database_id": WOS_DATABASE_ID, "retrieved_at": datetime.now(timezone.utc).isoformat(), "records": records,
                    })
                    st.success(f"WoS discovery: {len(records)} compact non-RC records.")
                if "Verify OMEGA identifiers" in workflows:
                    with tempfile.TemporaryDirectory() as tmp:
                        op = Path(tmp) / omega_upload.name
                        op.write_bytes(omega_upload.getvalue())
                        ids = sorted({r.wos_ut for r in omega_records(op) if r.wos_ut and not is_research_commons_uid(r.wos_ut)})
                    with st.spinner("WoS OMEGA-ID verification..."):
                        pages = client.get_by_ids(ids, database_id=WOS_DATABASE_ID, use_cache=False)
                    records = compact_wos_pages(pages, organization=WOS_ORG)
                    st.session_state["wos_live_payloads"].append({
                        "format": "monverify-wos-compact-v1", "mode": "omega_ids", "database_id": WOS_DATABASE_ID,
                        "requested_ids": ids, "retrieved_at": datetime.now(timezone.utc).isoformat(), "records": records,
                    })
                    st.success(f"OMEGA-ID verification: {len(records)} records returned.")
            except Exception as exc:
                st.error(_api_error_text(exc))

required = omega_upload is not None and quartile_upload is not None and scival_upload is not None
if st.button("Run verification", disabled=not required):
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp)
        omega_path = _save_upload(omega_upload, folder)
        quartile_path = _save_upload(quartile_upload, folder)
        scival_path = _save_upload(scival_upload, folder, "scival_")
        ministry_path = _save_upload(ministry_upload, folder, "ministry_") if ministry_upload else None
        manual_path = _save_upload(manual_upload, folder, "manual_") if manual_upload else None
        wos_paths: list[Path] = []
        if mode == "Uploaded/cached JSON":
            wos_paths = _save_uploads(wos_uploads, folder, "wos_")
        else:
            for i, payload in enumerate(st.session_state.get("wos_live_payloads", []), 1):
                p = folder / f"wos_live_{i}.json"
                p.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
                wos_paths.append(p)
        claim = parse_ministry_workbook(ministry_path) if ministry_path else RULES.ministry_claim()
        pubs = build_canonical_publications(
            omega_path=omega_path, quartiles_path=quartile_path, rules_path=RULES_PATH,
            wos_json=wos_paths, scival_csv=scival_path, manual_overrides_csv=manual_path,
        )
        st.session_state["claim"] = claim.model_dump()
        _recalculate(pubs, claim)

if "pubs" in st.session_state:
    pubs = [CanonicalPublication(**x) for x in st.session_state["pubs"]]
    claim = MinistryClaim(**st.session_state["claim"])
    agg = st.session_state["aggregate"]
    comparison = pd.DataFrame(st.session_state["comparison"])
    frame = publications_dataframe(pubs)
    united = united_verification_dataframe(pubs)

    st.subheader("MON vs calculated")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Resolved publications", agg["publication_count"], agg["publication_count"] - claim.publication_count)
    c2.metric("Q1 weighted", agg["weighted"]["a1"], round(agg["weighted"]["a1"] - claim.q1_weighted, 3))
    c3.metric("Q2 weighted", agg["weighted"]["a2"], round(agg["weighted"]["a2"] - claim.q2_weighted, 3))
    c4.metric("a score", agg["a_score"], round(agg["a_score"] - claim.a_score, 3))
    if agg["unresolved_institution_count"]:
        st.warning(f"{agg['unresolved_institution_count']} records remain unresolved because institution count is missing/zero.")
    else:
        st.success("All active records have institution counts; calculation is complete.")
    st.caption(
        f"Candidates: {agg['candidate_publication_count']} · resolved: {agg['confirmed_publication_count']} · "
        f"unresolved: {agg['unresolved_institution_count']} · removed: {agg['removed_publication_count']}"
    )
    st.dataframe(comparison, use_container_width=True, hide_index=True)

    tabs = st.tabs(["United table", "Manual review", "Canonical", "Discrepancies", ">10 institutions", "Removed", "Downloads"])
    with tabs[0]:
        st.caption("Resolved first, then unresolved; each group sorted alphabetically by source title.")
        st.dataframe(united, use_container_width=True, hide_index=True)

    with tabs[1]:
        st.caption("Enter a positive institution count to resolve a missing/zero count. Check Remove to exclude any record from the active corpus.")
        review_rows = []
        for p in pubs:
            review_rows.append({
                "canonical_id": p.canonical_id,
                "Source title": p.source_title or "",
                "Title": p.title or "",
                "WoS ID": p.wos_ut or "",
                "Scopus ID": p.scopus_id or "",
                "Scopus EID": p.scopus_eid or "",
                "Current institutions": p.selected_institution_count,
                "Manual institution count": p.manual_institution_count,
                "Remove": p.manually_removed,
                "Note": p.manual_note or "",
            })
        review_df = pd.DataFrame(review_rows)
        if not review_df.empty:
            review_df["_missing"] = review_df["Current institutions"].isna().astype(int)
            review_df = review_df.sort_values(["_missing", "Source title", "Title"], ascending=[False, True, True], key=lambda s: s.astype(str).str.casefold() if s.dtype == object else s).drop(columns="_missing")
        edited = st.data_editor(
            review_df,
            use_container_width=True,
            hide_index=True,
            disabled=["canonical_id", "Source title", "Title", "WoS ID", "Scopus ID", "Scopus EID", "Current institutions"],
            column_config={
                "Manual institution count": st.column_config.NumberColumn(min_value=1, step=1),
                "Remove": st.column_config.CheckboxColumn(),
            },
            key="manual_review_editor",
        )
        if st.button("Apply manual changes"):
            overrides: dict[str, dict[str, object]] = {}
            for _, row in edited.iterrows():
                count = row.get("Manual institution count")
                manual_count = int(count) if pd.notna(count) and str(count).strip() not in {"", "None", "nan"} else None
                overrides[str(row["canonical_id"])] = {
                    "manual_institution_count": manual_count,
                    "remove": bool(row.get("Remove")),
                    "note": str(row.get("Note", "")).strip() or None,
                }
            pubs = apply_manual_overrides(pubs, RULES, overrides)
            _recalculate(pubs, claim)
            st.rerun()

        override_export = edited.rename(columns={"Manual institution count": "manual_institution_count", "Remove": "remove", "Note": "note"})[["canonical_id", "manual_institution_count", "remove", "note"]]
        st.download_button("Download manual_overrides.csv", override_export.to_csv(index=False).encode("utf-8-sig"), "manual_overrides.csv", "text/csv")

    with tabs[2]:
        st.dataframe(frame, use_container_width=True, hide_index=True)
    with tabs[3]:
        discrepancies = frame[(frame["manually_removed"] != True) & (frame["discrepancy_codes"].fillna("").str.len() > 0)]  # noqa: E712
        st.dataframe(discrepancies, use_container_width=True, hide_index=True)
    with tabs[4]:
        over_10 = frame[(frame["manually_removed"] != True) & (frame["over_10_institutions"] == True)]  # noqa: E712
        st.dataframe(over_10, use_container_width=True, hide_index=True)
    with tabs[5]:
        removed = frame[frame["manually_removed"] == True]  # noqa: E712
        st.dataframe(removed, use_container_width=True, hide_index=True)
    with tabs[6]:
        unresolved = frame[(frame["manually_removed"] != True) & (frame["selected_institution_count"].isna())]  # noqa: E712
        removed = frame[frame["manually_removed"] == True]  # noqa: E712
        st.download_button("united_verification_table.csv", united.to_csv(index=False).encode("utf-8-sig"), "united_verification_table.csv", "text/csv")
        st.download_button("canonical_publications.csv", frame.to_csv(index=False).encode("utf-8-sig"), "canonical_publications.csv", "text/csv")
        st.download_button("ministry_comparison.csv", comparison.to_csv(index=False).encode("utf-8-sig"), "ministry_comparison.csv", "text/csv")
        st.download_button("unresolved_records.csv", unresolved.to_csv(index=False).encode("utf-8-sig"), "unresolved_records.csv", "text/csv")
        st.download_button("removed_records.csv", removed.to_csv(index=False).encode("utf-8-sig"), "removed_records.csv", "text/csv")
        summary = {"ministry_claim": claim.model_dump(), "calculated": agg}
        st.download_button("verification_summary.json", json.dumps(summary, ensure_ascii=False, indent=2).encode("utf-8"), "verification_summary.json", "application/json")
else:
    st.info("Upload OMEGA, quartiles and SciVal; add WoS evidence by upload or live API; then run verification.")
