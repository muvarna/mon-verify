from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Iterable

import requests

from ..models import SourceRecord
from ..normalization import normalize_doi, normalize_issn, normalize_title
from .common import cache_key, read_json, request_json, write_json

logger = logging.getLogger(__name__)


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _get_path(obj: Any, *keys: str) -> Any:
    cur = obj
    for key in keys:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return cur


def wos_records_from_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    candidates = [_get_path(payload, "Data", "Records", "records", "REC"),_get_path(payload, "Data", "Records", "records"),_get_path(payload, "Data", "Records"),payload.get("records")]
    for value in candidates:
        if isinstance(value, list):
            return [x for x in value if isinstance(x, dict)]
        if isinstance(value, dict):
            rec = value.get("REC")
            if isinstance(rec, list):
                return [x for x in rec if isinstance(x, dict)]
    return []


def _records_found(payload: dict[str, Any]) -> int | None:
    result = payload.get("QueryResult")
    if isinstance(result, dict):
        for key in ("RecordsFound", "recordsFound", "records_found"):
            value = result.get(key)
            if value is not None:
                try:
                    return int(value)
                except (TypeError, ValueError):
                    pass
    return None


def _title_of_type(record: dict[str, Any], wanted: str) -> str | None:
    titles = _get_path(record, "static_data", "summary", "titles", "title")
    for item in _as_list(titles):
        if not isinstance(item, dict):
            continue
        if str(item.get("type", "")).lower() == wanted.lower():
            value = item.get("content") or item.get("value")
            if value:
                return str(value)
    return None


def _find_identifier(record: dict[str, Any], types: set[str]) -> str | None:
    wanted = {x.lower() for x in types}
    def walk(value: Any) -> str | None:
        if isinstance(value, dict):
            type_value = str(value.get("type", "")).lower()
            if type_value in wanted:
                candidate = value.get("value") or value.get("content") or value.get("id")
                if candidate:
                    return str(candidate)
            for child in value.values():
                found = walk(child)
                if found:
                    return found
        elif isinstance(value, list):
            for child in value:
                found = walk(child)
                if found:
                    return found
        return None
    return walk(record)


def extract_wos_enhanced_institutions(record: dict[str, Any]) -> list[str]:
    addresses = _get_path(record, "static_data", "fullrecord_metadata", "addresses", "address_name")
    found: dict[str, str] = {}
    for address in _as_list(addresses):
        if not isinstance(address, dict):
            continue
        organizations = _get_path(address, "address_spec", "organizations", "organization")
        for org in _as_list(organizations):
            if not isinstance(org, dict) or str(org.get("pref", "")).upper() != "Y":
                continue
            name = org.get("content") or org.get("value")
            if name:
                ror = org.get("ror_id") or org.get("rorId")
                key = f"ror:{ror}" if ror else (normalize_title(name) or str(name).lower())
                found[key] = str(name).strip()
    return sorted(found.values(), key=str.lower)


def normalize_wos_record(record: dict[str, Any], organization: str = "Medical University Varna") -> SourceRecord:
    uid = str(record.get("UID") or record.get("uid") or "").strip() or None
    title = _title_of_type(record, "item")
    source_title = _title_of_type(record, "source")
    pub_info = _get_path(record, "static_data", "summary", "pub_info") or {}
    year_value = pub_info.get("pubyear") if isinstance(pub_info, dict) else None
    try:
        year = int(year_value) if year_value is not None else None
    except (TypeError, ValueError):
        year = None
    doctypes = _get_path(record, "static_data", "summary", "doctypes", "doctype")
    doc_list = [str(x.get("content") if isinstance(x, dict) else x) for x in _as_list(doctypes) if x]
    institutions = extract_wos_enhanced_institutions(record)
    organization_key = normalize_title(organization)
    muv = any(normalize_title(x) == organization_key for x in institutions) if institutions else None
    doi = normalize_doi(_find_identifier(record, {"doi"}))
    issn = normalize_issn(_find_identifier(record, {"issn"}))
    eissn = normalize_issn(_find_identifier(record, {"eissn", "e-issn"}))
    if uid:
        collection = "woscc" if uid.upper().startswith("WOS:") else "alldb"
        evidence_url = f"https://www.webofscience.com/wos/{collection}/full-record/{uid}"
    else:
        evidence_url = None
    return SourceRecord(source="wos",source_id=uid or f"wos:{normalize_title(title) or 'unknown'}",doi=doi,wos_ut=uid,title=title,normalized_title=normalize_title(title),year=year,document_type="; ".join(doc_list) if doc_list else None,source_title=source_title,issn=issn,eissn=eissn,muv_affiliation=muv,institution_count=len(institutions) if institutions else None,institutions=institutions,evidence_url=evidence_url,raw=record)


class WOSClient:
    def __init__(self, api_key: str, *, base_url: str = "https://api.clarivate.com/api/wos/", cache_dir: str | Path = "data/raw/wos", session: requests.Session | None = None) -> None:
        if not api_key:
            raise ValueError("WOS API key is required")
        self.api_key = api_key
        self.base_url = base_url.rstrip("/") + "/"
        self.cache_dir = Path(cache_dir)
        self.session = session or requests.Session()

    @property
    def headers(self) -> dict[str, str]:
        return {"X-ApiKey": self.api_key, "Accept": "application/json"}

    def search_pages(self, query: str, *, database_id: str = "WOS", count: int = 100, use_cache: bool = True, max_records: int | None = None) -> list[dict[str, Any]]:
        if count < 1 or count > 100:
            raise ValueError("WoS Expanded count must be between 1 and 100")
        pages: list[dict[str, Any]] = []
        first_record = 1
        total: int | None = None
        retrieved = 0
        while total is None or first_record <= total:
            if max_records is not None and retrieved >= max_records:
                break
            page_count = count if max_records is None else min(count, max_records - retrieved)
            if page_count <= 0:
                break
            params = {"databaseId": database_id,"usrQuery": query,"count": page_count,"firstRecord": first_record,"lang": "en"}
            cache_path = self.cache_dir / cache_key("search", params)
            if use_cache and cache_path.exists():
                payload = read_json(cache_path)
            else:
                payload, _ = request_json(self.session, "GET", self.base_url, params=params, headers=self.headers)
                if use_cache:
                    write_json(cache_path, payload)
            pages.append(payload)
            records = wos_records_from_payload(payload)
            if total is None:
                total = _records_found(payload)
            retrieved += len(records)
            if not records:
                break
            first_record += len(records)
            if total is None and len(records) < page_count:
                break
        return pages

    def get_by_ids(self, unique_ids: Iterable[str], *, database_id: str = "WOK", batch_size: int = 100, use_cache: bool = True) -> list[dict[str, Any]]:
        ids = [str(x).strip() for x in unique_ids if str(x).strip()]
        pages: list[dict[str, Any]] = []
        for pos in range(0, len(ids), batch_size):
            batch = ids[pos:pos + batch_size]
            params = {"databaseId": database_id, "count": max(1, len(batch)), "firstRecord": 1}
            url = self.base_url.rstrip("/") + "/id/" + ",".join(batch)
            cache_params = {"ids": batch, **params}
            cache_path = self.cache_dir / cache_key("ids", cache_params)
            if use_cache and cache_path.exists():
                payload = read_json(cache_path)
            else:
                payload, _ = request_json(self.session, "GET", url, params=params, headers=self.headers)
                if use_cache:
                    write_json(cache_path, payload)
            pages.append(payload)
        return pages

    def search_records(self, query: str, **kwargs: Any) -> list[SourceRecord]:
        pages = self.search_pages(query, **kwargs)
        return [normalize_wos_record(record) for page in pages for record in wos_records_from_payload(page)]
