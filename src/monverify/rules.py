from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml

from .models import MinistryClaim


class RuleEngine:
    def __init__(self, rules: dict[str, Any]):
        self.rules = rules

    @classmethod
    def from_yaml(cls, path: str | Path) -> "RuleEngine":
        with Path(path).open("r", encoding="utf-8") as fh:
            return cls(yaml.safe_load(fh))

    @property
    def assessment_year(self) -> int:
        return int(self.rules["assessment_year"])

    @property
    def threshold(self) -> int:
        return int(self.rules["institution_rule"]["threshold"])

    def ministry_claim(self) -> MinistryClaim:
        values = dict(self.rules.get("ministry_claim") or {})
        if not values:
            raise ValueError("Rules file does not contain ministry_claim")
        values["assessment_year"] = self.assessment_year
        return MinistryClaim(**values)

    def is_over_threshold(self, institution_count: int | None) -> bool | None:
        if institution_count is None:
            return None
        return institution_count > self.threshold

    def multiplier(self, institution_count: int | None) -> float | None:
        if institution_count is None:
            return None
        if institution_count > self.threshold:
            return float(self.rules["institution_rule"]["over_threshold_multiplier"])
        return float(self.rules["institution_rule"]["normal_multiplier"])

    def bucket_for_quartile(self, quartile: str | None) -> str:
        key = quartile if quartile in {"Q1", "Q2", "Q3", "Q4"} else "NONE"
        return str(self.rules["quartiles"][key])

    def bucket_weight(self, bucket: str) -> float:
        return float(self.rules["formula"][bucket])

    def score(self, weighted_buckets: dict[str, float]) -> float:
        total = Decimal("0")
        for bucket in ("a1", "a2", "a3", "a4"):
            amount = Decimal(str(weighted_buckets.get(bucket, 0.0)))
            weight = Decimal(str(self.rules["formula"][bucket]))
            total += amount * weight
        return float(total)
