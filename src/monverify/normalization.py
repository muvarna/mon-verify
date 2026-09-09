from __future__ import annotations

import re
import unicodedata


def empty_to_none(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in {"nan", "n/a", "na", "none", "null"}:
        return None
    return text


def normalize_doi(value: object) -> str | None:
    text = empty_to_none(value)
    if not text:
        return None
    text = text.strip().lower()
    text = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", text)
    text = re.sub(r"^doi\s*:\s*", "", text)
    text = text.strip().rstrip(".,;)")
    if not re.match(r"^10\.\d{4,9}/\S+$", text, flags=re.I):
        return None
    return text


def normalize_issn(value: object) -> str | None:
    text = empty_to_none(value)
    if not text:
        return None
    compact = re.sub(r"[^0-9Xx]", "", text).upper()
    return compact if len(compact) == 8 else None


def display_issn(value: object) -> str | None:
    compact = normalize_issn(value)
    if not compact:
        return None
    return f"{compact[:4]}-{compact[4:]}"


def normalize_title(value: object) -> str | None:
    text = empty_to_none(value)
    if not text:
        return None
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = text.lower().replace("&", " and ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip() or None


def normalize_quartile(value: object) -> str | None:
    text = empty_to_none(value)
    if not text:
        return None
    m = re.search(r"(?:Q\s*)?([1-4])", text, flags=re.I)
    return f"Q{m.group(1)}" if m else None
