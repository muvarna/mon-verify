from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import requests

from ..models import SourceRecord
from ..normalization import empty_to_none, normalize_doi, normalize_issn, normalize_title
from .common import cache_key, read_json, request_json, write_json

logger = logging.getLogger(__name__)


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def scopus_entries_from_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    results = payload.get("search-results")
    if isinstance(results, dict):
        entries = results.get("entry")
        if isinstance(entries, list):
            return [x for x in entries if isinstance(x, dict)]
        if isinstance(entries, dict):
            return [entries]
    entries = payload.get("entries")
    return [x for x in entries if isinstance(x, dict)] if isinstance(entries, list) else []


def _total_results(payload: dict[str, Any]) -> int | None:
    results = payload.get("search-results")
    if isinstance(results, dict):
        value = results.get("opensearch:totalResults")
        try:
            return int(value)
        except (TypeError, ValueError):
            pass
    return None


def _next_cursor(payload: dict[str, Any]) -> str | None:
    results = payload.get("search-results")
    if not isinstance(results, dict):
        return None
    cursor = results.get("cursor")
    if isinstance(cursor, dict):
        value = cursor.get("@next") or cursor.get("next")
        return str(value) if value else None
    return None


def _scopus_id(entry: dict[str, Any]) -> str | None:
    raw = empty_to_none(entry.get("dc:identifier"))
    if raw and raw.upper().startswith("SCOPUS_ID:"):
        return raw.split(":", 1)[1]
    return raw


def _affiliations(entry: dict[str, Any]) -> tuple[list[str], list[str]]:
    names: dict[str, str] = {}
    ids: dict[str, str] = {}
    for item in _as_list(entry.get("affiliation")):
        if not isinstance(item, dict):
            continue
        aff_id = empty_to_none(item.get("affiliation-id") or item.get("@id"))
        name = empty_to_none(item.get("affilname") or item.get("affiliation-name"))
        if aff_id:
            ids[aff_id] = aff_id
        if name:
            names[normalize_title(name) or name.lower()] = name
    return sorted(names.values(), key=str.lower), sorted(ids.values())


def _evidence_url(entry: dict[str, Any], eid: str | None) -> str | None:
    for link in _as_list(entry.get("link")):
        if isinstance(link, dict):
            href = empty_to_none(link.get("@href") or link.get("href"))
            ref = str(link.get("@ref") or link.get("ref") or "").lower()
            if href and ref in {"scopus", "record"}:
                return href
    return f"https://www.scopus.com/record/display.uri?eid={eid}&origin=resultslist" if eid else None


def normalize_scopus_entry(entry: dict[str, Any], affiliation_id: str = "60005828") -> SourceRecord:
    scopus_id = _scopus_id(entry)
    eid = empty_to_none(entry.get("eid"))
    title = empty_to_none(entry.get("dc:title"))
    cover_date = empty_to_none(entry.get("prism:coverDate"))
    try:
        year = int(cover_date[:4]) if cover_date else None
    except ValueError:
        year = None
    names, ids = _affiliations(entry)
    muv = affiliation_id in ids if ids else None
    return SourceRecord(source="scopus",source_id=eid or scopus_id or f"scopus:{normalize_title(title) or 'unknown'}",doi=normalize_doi(entry.get("prism:doi")),scopus_id=scopus_id,scopus_eid=eid,title=title,normalized_title=normalize_title(title),year=year,document_type=empty_to_none(entry.get("subtypeDescription") or entry.get("subtype")),source_title=empty_to_none(entry.get("prism:publicationName")),issn=normalize_issn(entry.get("prism:issn")),eissn=normalize_issn(entry.get("prism:eIssn") or entry.get("prism:eissn")),muv_affiliation=muv,institution_count=len(ids) if ids else None,institutions=names,evidence_url=_evidence_url(entry, eid),raw=entry)


def normalize_scopus_abstract(payload: dict[str, Any], affiliation_id: str = "60005828") -> SourceRecord:
    root = payload.get("abstracts-retrieval-response") if isinstance(payload, dict) else None
    if not isinstance(root, dict):
        root = payload
    core = root.get("coredata") if isinstance(root, dict) else None
    entry = dict(core) if isinstance(core, dict) else {}
    if isinstance(root, dict):
        affiliation = root.get("affiliation")
        if affiliation is not None:
            entry["affiliation"] = affiliation
    return normalize_scopus_entry(entry, affiliation_id=affiliation_id)


class ScopusClient:
    def __init__(self, api_key: str, *, insttoken: str | None = None, base_url: str = "https://api.elsevier.com/content/search/scopus", abstract_base_url: str = "https://api.elsevier.com/content/abstract/scopus_id", cache_dir: str | Path = "data/raw/scopus", session: requests.Session | None = None) -> None:
        if not api_key:
            raise ValueError("Scopus API key is required")
        self.api_key = api_key
        self.insttoken = insttoken
        self.base_url = base_url
        self.abstract_base_url = abstract_base_url.rstrip("/")
        self.cache_dir = Path(cache_dir)
        self.session = session or requests.Session()

    @property
    def headers(self) -> dict[str, str]:
        headers = {"X-ELS-APIKey": self.api_key, "Accept": "application/json"}
        if self.insttoken:
            headers["X-ELS-Insttoken"] = self.insttoken
        return headers

    def search_pages(self, query: str, *, count: int = 25, use_cache: bool = True, max_records: int | None = None) -> list[dict[str, Any]]:
        pages: list[dict[str, Any]] = []
        cursor: str | None = "*"
        start = 0
        retrieved = 0
        total: int | None = None
        while total is None or retrieved < total:
            if max_records is not None and retrieved >= max_records:
                break
            page_count = count if max_records is None else min(count, max_records - retrieved)
            if page_count <= 0:
                break
            params: dict[str, Any] = {"query": query, "count": page_count, "view": "COMPLETE"}
            if cursor:
                params["cursor"] = cursor
            else:
                params["start"] = start
            cache_path = self.cache_dir / cache_key("search", params)
            if use_cache and cache_path.exists():
                payload = read_json(cache_path)
            else:
                payload, _ = request_json(self.session, "GET", self.base_url, params=params, headers=self.headers)
                if use_cache:
                    write_json(cache_path, payload)
            pages.append(payload)
            entries = scopus_entries_from_payload(payload)
            if total is None:
                total = _total_results(payload)
            if not entries:
                break
            retrieved += len(entries)
            next_cursor = _next_cursor(payload)
            if cursor and next_cursor and next_cursor != cursor:
                cursor = next_cursor
            else:
                cursor = None
                start = retrieved
            if total is None and len(entries) < page_count:
                break
        return pages

    def retrieve_abstract(self, scopus_id: str, *, use_cache: bool = True) -> dict[str, Any]:
        sid = str(scopus_id).strip()
        params = {"view": "FULL"}
        cache_path = self.cache_dir / cache_key("abstract", {"scopus_id": sid, **params})
        if use_cache and cache_path.exists():
            return read_json(cache_path)
        url = f"{self.abstract_base_url}/{sid}"
        payload, _ = request_json(self.session, "GET", url, params=params, headers=self.headers)
        if use_cache:
            write_json(cache_path, payload)
        return payload

    def retrieve_many(self, scopus_ids: list[str], *, use_cache: bool = True) -> list[dict[str, Any]]:
        responses: list[dict[str, Any]] = []
        for sid in scopus_ids:
            try:
                responses.append(self.retrieve_abstract(sid, use_cache=use_cache))
            except Exception as exc:
                logger.error("Scopus abstract retrieval failed for %s: %s", sid, exc)
                responses.append({"_monverify_error": str(exc), "_requested_scopus_id": str(sid)})
        return responses

    def search_records(self, query: str, *, affiliation_id: str = "60005828", **kwargs: Any) -> list[SourceRecord]:
        pages = self.search_pages(query, **kwargs)
        return [normalize_scopus_entry(entry, affiliation_id=affiliation_id) for page in pages for entry in scopus_entries_from_payload(page)]
