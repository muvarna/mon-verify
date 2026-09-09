from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

from .models import MinistryClaim


def _number(value: object) -> float | None:
    if value is None or pd.isna(value):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).replace(",", ".").strip())
    except ValueError:
        return None


def _weighted_expression(text: str) -> tuple[float | None, int]:
    m = re.search(r"(\d+(?:\.\d+)?)\s*-\s*(\d+)\s*\+\s*0[.,]1\s*\*\s*(\d+)", text)
    if not m:
        m2 = re.search(r"\b(\d+(?:\.\d+)?)\b", text)
        return (float(m2.group(1)) if m2 else None, 0)
    raw, reduced, repeated = float(m.group(1)), int(m.group(2)), int(m.group(3))
    if reduced != repeated:
        raise ValueError(f"Unexpected Ministry weighting expression: {text}")
    return raw, reduced


def parse_ministry_workbook(path: str | Path) -> MinistryClaim:
    workbook = pd.ExcelFile(path)
    rows: list[list[object]] = []
    for sheet in workbook.sheet_names:
        frame = pd.read_excel(path, sheet_name=sheet, header=None)
        rows.extend(frame.values.tolist())
    year = None
    publication_count = None
    score = None
    q1_raw = q2_raw = None
    q1_over = q2_over = 0
    q1_weighted = q2_weighted = q3 = a4 = None
    for row in rows:
        text_cells = [str(x) for x in row if x is not None and not pd.isna(x)]
        joined = " | ".join(text_cells)
        if year is None:
            m = re.search(r"Период\s*:\s*(20\d{2})", joined, flags=re.I)
            if m:
                year = int(m.group(1))
        if "Брой научни публикации" in joined:
            nums = [_number(x) for x in row]
            nums = [x for x in nums if x is not None]
            if len(nums) >= 2:
                publication_count = int(nums[-2])
                score = float(nums[-1])
        if "категория Q1" in joined:
            q1_raw, q1_over = _weighted_expression(joined)
            vals = [_number(x) for x in row]
            vals = [x for x in vals if x is not None]
            if vals:
                q1_weighted = vals[-1]
        if "категория Q2" in joined:
            q2_raw, q2_over = _weighted_expression(joined)
            vals = [_number(x) for x in row]
            vals = [x for x in vals if x is not None]
            if vals:
                q2_weighted = vals[-1]
        if "категория Q3" in joined:
            vals = [_number(x) for x in row]
            vals = [x for x in vals if x is not None]
            if vals:
                q3 = vals[-1]
        if "всички останали публикации" in joined:
            vals = [_number(x) for x in row]
            vals = [x for x in vals if x is not None]
            if vals:
                a4 = vals[-1]
    missing = {"assessment_year": year,"publication_count": publication_count,"a_score": score,"q1_raw": q1_raw,"q1_weighted": q1_weighted,"q2_raw": q2_raw,"q2_weighted": q2_weighted,"q3": q3,"a4": a4}
    absent = [k for k, v in missing.items() if v is None]
    if absent:
        raise ValueError(f"Could not parse Ministry workbook fields: {', '.join(absent)}")
    return MinistryClaim(assessment_year=int(year),publication_count=int(publication_count),q1_raw=float(q1_raw),q1_over_10=q1_over,q1_weighted=float(q1_weighted),q2_raw=float(q2_raw),q2_over_10=q2_over,q2_weighted=float(q2_weighted),q3_raw=float(q3),q3_weighted=float(q3),a4_raw=float(a4),a4_weighted=float(a4),a_score=float(score))
