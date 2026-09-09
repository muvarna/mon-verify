from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from .models import CanonicalPublication, MinistryClaim
from .rules import RuleEngine
from .verification import aggregate, compare_to_ministry


def _publication_row(pub: CanonicalPublication) -> dict[str, Any]:
    data = pub.model_dump()
    data["source_years"] = json.dumps(data["source_years"], ensure_ascii=False, sort_keys=True)
    data["discrepancy_codes"] = ";".join(data["discrepancy_codes"])
    data["evidence_urls"] = ";".join(data["evidence_urls"])
    data["provenance"] = json.dumps(data["provenance"], ensure_ascii=False)
    return data


def publications_dataframe(publications: Iterable[CanonicalPublication]) -> pd.DataFrame:
    return pd.DataFrame([_publication_row(p) for p in publications])



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
        "discrepancy_record_count": int(len(corrections_df)),
        "unresolved_record_count": int(len(unresolved_df)),
        "over_10_record_count": int(len(weighted_df)),
    }
    summary_path = out / "verification_summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "canonical": canonical_path,
        "comparison": comparison_path,
        "corrections": corrections_path,
        "unresolved": unresolved_path,
        "over_10": weighted_path,
        "summary": summary_path,
    }
