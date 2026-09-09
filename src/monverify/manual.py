from __future__ import annotations

from pathlib import Path

import pandas as pd

from .models import CanonicalPublication
from .rules import RuleEngine

OVERRIDE_COLUMNS = ["canonical_id", "manual_institution_count", "remove", "note"]


def load_manual_overrides(path: str | Path | None) -> dict[str, dict[str, object]]:
    if not path:
        return {}
    p = Path(path)
    if not p.exists():
        return {}
    frame = pd.read_csv(p, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    frame.columns = [str(c).strip() for c in frame.columns]
    if "canonical_id" not in frame.columns:
        raise ValueError("manual_overrides.csv must contain canonical_id")
    out: dict[str, dict[str, object]] = {}
    for _, row in frame.iterrows():
        cid = str(row.get("canonical_id", "")).strip()
        if not cid:
            continue
        count_text = str(row.get("manual_institution_count", "")).strip()
        count = None
        if count_text:
            try:
                value = int(float(count_text))
                count = value if value > 0 else None
            except ValueError as exc:
                raise ValueError(f"Invalid manual institution count for {cid}: {count_text!r}") from exc
        remove_text = str(row.get("remove", "")).strip().lower()
        remove = remove_text in {"1", "true", "yes", "y", "x"}
        note = str(row.get("note", "")).strip() or None
        out[cid] = {"manual_institution_count": count, "remove": remove, "note": note}
    return out


def apply_manual_overrides(publications: list[CanonicalPublication], rules: RuleEngine, overrides: dict[str, dict[str, object]]) -> list[CanonicalPublication]:
    for pub in publications:
        override = overrides.get(pub.canonical_id)
        if not override:
            continue
        pub.manual_note = override.get("note") if isinstance(override.get("note"), str) else None
        if bool(override.get("remove")):
            pub.manually_removed = True
            pub.eligible_for_calculation = False
            pub.eligibility_reason = "Manually removed from verification corpus"
            pub.verification_status = "removed"
            pub.discrepancy_codes = sorted(set(pub.discrepancy_codes + ["MANUALLY_REMOVED"]))
            continue
        count = override.get("manual_institution_count")
        if isinstance(count, int) and count > 0:
            pub.manual_institution_count = count
            pub.selected_institution_count = count
            pub.institution_count_source = "manual"
            pub.over_10_institutions = rules.is_over_threshold(count)
            pub.contribution_multiplier = rules.multiplier(count)
            pub.weighted_contribution = pub.contribution_multiplier
            pub.score_contribution = pub.contribution_multiplier * rules.bucket_weight(pub.ministry_bucket or "a4") if pub.contribution_multiplier is not None else None
            pub.eligible_for_calculation = True
            pub.eligibility_reason = "Institution count supplied manually"
            pub.verification_status = "confirmed"
            pub.discrepancy_codes = [x for x in pub.discrepancy_codes if x != "MISSING_INSTITUTION_COUNT"]
            pub.discrepancy_codes = sorted(set(pub.discrepancy_codes + ["MANUAL_INSTITUTION_COUNT"]))
    return publications


def overrides_template(publications: list[CanonicalPublication]) -> pd.DataFrame:
    rows = []
    for pub in publications:
        if pub.selected_institution_count is not None and not pub.manually_removed:
            continue
        rows.append({
            "canonical_id": pub.canonical_id,
            "source_title": pub.source_title or "",
            "title": pub.title or "",
            "wos_ut": pub.wos_ut or "",
            "scopus_id": pub.scopus_id or "",
            "scopus_eid": pub.scopus_eid or "",
            "manual_institution_count": pub.manual_institution_count or "",
            "remove": pub.manually_removed,
            "note": pub.manual_note or "",
        })
    return pd.DataFrame(rows)
