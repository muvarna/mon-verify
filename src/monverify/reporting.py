from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from .models import CanonicalPublication, MinistryClaim
from .omega import OMEGA_COLUMN_ORDER
from .rules import RuleEngine
from .verification import aggregate, compare_to_ministry


def _publication_row(pub: CanonicalPublication) -> dict[str, Any]:
    data = pub.model_dump()
    data["source_years"] = json.dumps(data["source_years"], ensure_ascii=False, sort_keys=True)
    data["muv_authors_wos"] = "; ".join(data.get("muv_authors_wos") or [])
    data["omega_original"] = json.dumps(data.get("omega_original") or {}, ensure_ascii=False)
    data["discrepancy_codes"] = ";".join(data["discrepancy_codes"])
    data["evidence_urls"] = ";".join(data["evidence_urls"])
    data["provenance"] = json.dumps(data["provenance"], ensure_ascii=False)
    return data


def publications_dataframe(publications: Iterable[CanonicalPublication]) -> pd.DataFrame:
    return pd.DataFrame([_publication_row(p) for p in publications])


def _provenance_url(pub: CanonicalPublication, source: str) -> str:
    for item in pub.provenance:
        if item.get("source") == source and item.get("evidence_url"):
            return str(item["evidence_url"])
    return ""


def _verified_wos_url(pub: CanonicalPublication) -> str:
    url = _provenance_url(pub, "wos")
    if url:
        return url
    uid = (pub.wos_ut or "").strip()
    if not uid or uid.upper().startswith("RC"):
        return ""
    collection = "woscc" if uid.upper().startswith("WOS:") else "alldb"
    return f"https://www.webofscience.com/wos/{collection}/full-record/{uid}"


def _verified_scopus_url(pub: CanonicalPublication) -> str:
    url = _provenance_url(pub, "scopus")
    if url:
        return url
    eid = (pub.scopus_eid or "").strip()
    if eid:
        return f"https://www.scopus.com/record/display.uri?eid={eid}&origin=resultslist"
    sid = (pub.scopus_id or "").strip()
    if sid:
        return f"https://www.scopus.com/inward/record.uri?scp={sid}&partnerID=HzOxMe3b&origin=inward"
    return ""


def _preferred_year(pub: CanonicalPublication) -> int | None:
    for source in ("wos", "scopus", "omega"):
        value = pub.source_years.get(source)
        if value is not None:
            return value
    return next((value for value in pub.source_years.values() if value is not None), None)


def _review_group(pub: CanonicalPublication) -> str:
    if pub.verification_status in {"confirmed", "strongly_supported"}:
        return "Confirmed"
    if pub.verification_status in {"manual_review", "ambiguous"} or pub.eligible_for_calculation is None:
        return "Unresolved"
    return "Excluded"


def united_verification_dataframe(publications: Iterable[CanonicalPublication]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for pub in publications:
        omega = pub.omega_original or {}
        has_omega = bool(omega)
        row: dict[str, Any] = {}

        # Preserve the original OMEGA values when the record came from OMEGA.
        # For independently discovered records, populate the OMEGA-shaped columns
        # only with canonical metadata that is directly available.
        row["Reference"] = omega.get("Reference", "") if has_omega else (pub.title or "")
        row["Journal"] = omega.get("Journal", "") if has_omega else (pub.source_title or "")
        row["publicationType"] = omega.get("publicationType", "") if has_omega else (pub.document_type or "")
        row["Issue year"] = omega.get("Issue year", "") if has_omega else (_preferred_year(pub) or "")
        row["DOI"] = omega.get("DOI", "") if has_omega else (pub.doi or "")
        row["WoSId"] = omega.get("WoSId", "") if has_omega else (pub.wos_ut or "")
        row["ScopusId"] = omega.get("ScopusId", "") if has_omega else (pub.scopus_id or pub.scopus_eid or "")
        row["JIFQuartile"] = omega.get("JIFQuartile", "") if has_omega else (pub.jif_quartile or "")
        row["Authors MU-Varna"] = omega.get("Authors MU-Varna", "") if has_omega else (pub.omega_authors or "")

        # The OMEGA link columns are the primary source-specific evidence fields.
        # Prefer a verified URL produced from WoS/Scopus evidence. If that source
        # is not verified for this publication, retain the original OMEGA link.
        verified_wos_url = _verified_wos_url(pub)
        verified_scopus_url = _verified_scopus_url(pub)
        row["Link WOS"] = verified_wos_url or (omega.get("Link WOS", "") if has_omega else "")
        row["Link Scopus"] = verified_scopus_url or (omega.get("Link Scopus", "") if has_omega else "")

        row["MUV authors WOS"] = "; ".join(pub.muv_authors_wos)
        row["Review group"] = _review_group(pub)
        row["Verification status"] = pub.verification_status
        row["Eligible"] = pub.eligible_for_calculation
        row["Eligibility reason"] = pub.eligibility_reason or ""
        row["Verified title"] = pub.title or ""
        row["Verified source title"] = pub.source_title or ""
        row["Verified year(s)"] = json.dumps(pub.source_years, ensure_ascii=False, sort_keys=True)
        row["Verified DOI"] = pub.doi or ""
        row["Verified WoSId"] = pub.wos_ut or ""
        row["Verified ScopusId"] = pub.scopus_id or pub.scopus_eid or ""
        row["Verified JIF Quartile"] = pub.jif_quartile or ""
        row["Quartile match method"] = pub.quartile_match_method or ""
        row["Quartile match confidence"] = pub.quartile_match_confidence or ""
        row["WoS institution count"] = pub.wos_institution_count
        row["Scopus institution count"] = pub.scopus_institution_count
        row["SciVal institution count"] = pub.scival_institution_count
        row["Selected institution count"] = pub.selected_institution_count
        row["Institution count source"] = pub.institution_count_source or ""
        row["Over 10 institutions"] = pub.over_10_institutions
        row["Ministry bucket"] = pub.ministry_bucket or ""
        row["Contribution multiplier"] = pub.contribution_multiplier
        row["Weighted contribution"] = pub.weighted_contribution
        row["Score contribution"] = pub.score_contribution
        row["In OMEGA"] = pub.in_omega
        row["In WoS"] = pub.in_wos
        row["In Scopus"] = pub.in_scopus
        row["Discrepancy codes"] = ";".join(pub.discrepancy_codes)
        row["Canonical ID"] = pub.canonical_id
        row["Evidence links"] = ";".join(pub.evidence_urls)
        rows.append(row)

    columns = OMEGA_COLUMN_ORDER + [
        "MUV authors WOS",
        "Review group",
        "Verification status",
        "Eligible",
        "Eligibility reason",
        "Verified title",
        "Verified source title",
        "Verified year(s)",
        "Verified DOI",
        "Verified WoSId",
        "Verified ScopusId",
        "Verified JIF Quartile",
        "Quartile match method",
        "Quartile match confidence",
        "WoS institution count",
        "Scopus institution count",
        "SciVal institution count",
        "Selected institution count",
        "Institution count source",
        "Over 10 institutions",
        "Ministry bucket",
        "Contribution multiplier",
        "Weighted contribution",
        "Score contribution",
        "In OMEGA",
        "In WoS",
        "In Scopus",
        "Discrepancy codes",
        "Canonical ID",
        "Evidence links",
    ]
    frame = pd.DataFrame(rows, columns=columns)
    if frame.empty:
        return frame

    order = {"Confirmed": 0, "Unresolved": 1, "Excluded": 2}
    frame["_review_order"] = frame["Review group"].map(order).fillna(9)
    frame["_title_order"] = frame["Verified title"].fillna("").astype(str).str.lower()
    frame = frame.sort_values(["_review_order", "_title_order", "Canonical ID"], kind="stable")
    return frame.drop(columns=["_review_order", "_title_order"]).reset_index(drop=True)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git_commit() -> str | None:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL).strip()
    except Exception:
        return None


def _input_metadata(source_files: dict[str, Any] | None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not source_files:
        return rows
    for role, value in source_files.items():
        values = value if isinstance(value, (list, tuple)) else [value]
        for item in values:
            if not item:
                continue
            path = Path(item)
            if not path.exists():
                continue
            row: dict[str, Any] = {
                "role": role,
                "file_name": path.name,
                "sha256": _sha256(path),
                "size_bytes": path.stat().st_size,
            }
            if path.suffix.lower() == ".json":
                try:
                    payload = json.loads(path.read_text(encoding="utf-8"))
                    for key in ("mode", "query", "database_id", "retrieved_at"):
                        if isinstance(payload, dict) and payload.get(key) is not None:
                            row[key] = payload.get(key)
                except Exception:
                    pass
            rows.append(row)
    return rows


def write_reports(
    publications: list[CanonicalPublication],
    claim: MinistryClaim,
    rules: RuleEngine,
    output_dir: str | Path,
    *,
    source_files: dict[str, Any] | None = None,
) -> dict[str, Path]:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    canonical_df = publications_dataframe(publications)
    canonical_path = out / "canonical_publications.csv"
    canonical_df.to_csv(canonical_path, index=False, encoding="utf-8-sig")

    united_df = united_verification_dataframe(publications)
    united_path = out / "united_verification_table.csv"
    united_df.to_csv(united_path, index=False, encoding="utf-8-sig")

    comparison_rows = compare_to_ministry(publications, claim, rules)
    comparison_df = pd.DataFrame(comparison_rows)
    comparison_path = out / "ministry_comparison.csv"
    comparison_df.to_csv(comparison_path, index=False, encoding="utf-8-sig")

    correction_mask = canonical_df["discrepancy_codes"].fillna("").astype(str).str.len() > 0 if not canonical_df.empty else []
    corrections_df = canonical_df.loc[correction_mask].copy() if not canonical_df.empty else canonical_df.copy()
    corrections_path = out / "ministry_corrections.csv"
    corrections_df.to_csv(corrections_path, index=False, encoding="utf-8-sig")

    unresolved_df = canonical_df[
        canonical_df["verification_status"].isin(["manual_review", "ambiguous"])
    ].copy() if not canonical_df.empty else canonical_df.copy()
    unresolved_path = out / "unresolved_records.csv"
    unresolved_df.to_csv(unresolved_path, index=False, encoding="utf-8-sig")

    weighted_df = canonical_df[canonical_df["over_10_institutions"] == True].copy() if not canonical_df.empty else canonical_df.copy()  # noqa: E712
    weighted_path = out / "over_10_institutions.csv"
    weighted_df.to_csv(weighted_path, index=False, encoding="utf-8-sig")

    summary = {
        "run_timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "git_commit": _git_commit(),
        "assessment_year": claim.assessment_year,
        "rules_version": rules.rules.get("version"),
        "inputs": _input_metadata(source_files),
        "ministry_claim": claim.model_dump(),
        "calculated": aggregate(publications, rules),
        "comparison": comparison_rows,
        "verification_status_counts": canonical_df["verification_status"].value_counts(dropna=False).to_dict() if not canonical_df.empty else {},
        "review_group_counts": united_df["Review group"].value_counts(dropna=False).to_dict() if not united_df.empty else {},
        "discrepancy_record_count": int(len(corrections_df)),
        "unresolved_record_count": int(len(unresolved_df)),
        "over_10_record_count": int(len(weighted_df)),
    }
    summary_path = out / "verification_summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "canonical": canonical_path,
        "united": united_path,
        "comparison": comparison_path,
        "corrections": corrections_path,
        "unresolved": unresolved_path,
        "over_10": weighted_path,
        "summary": summary_path,
    }
