from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


SourceName = Literal["omega", "wos", "scopus", "scival"]


class MinistryClaim(BaseModel):
    assessment_year: int
    publication_count: int
    q1_raw: float
    q1_over_10: int = 0
    q1_weighted: float
    q2_raw: float
    q2_over_10: int = 0
    q2_weighted: float
    q3_raw: float
    q3_weighted: float
    a4_raw: float
    a4_weighted: float
    a_score: float


class SourceRecord(BaseModel):
    source: SourceName
    source_id: str
    doi: str | None = None
    wos_ut: str | None = None
    scopus_id: str | None = None
    scopus_eid: str | None = None
    title: str | None = None
    normalized_title: str | None = None
    year: int | None = None
    document_type: str | None = None
    source_title: str | None = None
    issn: str | None = None
    eissn: str | None = None
    muv_affiliation: bool | None = None
    institution_count: int | None = None
    institutions: list[str] = Field(default_factory=list)
    omega_jif_quartile: str | None = None
    omega_authors: str | None = None
    evidence_url: str | None = None
    raw: dict[str, Any] | None = None


class CanonicalPublication(BaseModel):
    canonical_id: str
    doi: str | None = None
    wos_ut: str | None = None
    scopus_id: str | None = None
    scopus_eid: str | None = None
    title: str | None = None
    normalized_title: str | None = None
    source_years: dict[str, int | None] = Field(default_factory=dict)
    document_type: str | None = None
    source_title: str | None = None
    issn: str | None = None
    eissn: str | None = None
    in_omega: bool = False
    in_wos: bool = False
    in_scopus: bool = False
    eligible_for_calculation: bool | None = None
    eligibility_reason: str | None = None
    muv_affiliation_wos: bool | None = None
    muv_affiliation_scopus: bool | None = None
    omega_jif_quartile: str | None = None
    jif_quartile: str | None = None
    quartile_match_method: str | None = None
    quartile_match_confidence: str | None = None
    wos_institution_count: int | None = None
    scopus_institution_count: int | None = None
    scival_institution_count: int | None = None
    selected_institution_count: int | None = None
    institution_count_source: str | None = None
    over_10_institutions: bool | None = None
    ministry_bucket: str | None = None
    contribution_multiplier: float | None = None
    weighted_contribution: float | None = None
    score_contribution: float | None = None
    discrepancy_codes: list[str] = Field(default_factory=list)
    verification_status: str = "manual_review"
    evidence_urls: list[str] = Field(default_factory=list)
    provenance: list[dict[str, Any]] = Field(default_factory=list)
