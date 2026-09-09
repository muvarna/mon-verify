from __future__ import annotations

import hashlib
from collections import defaultdict

from .models import SourceRecord
from .normalization import normalize_doi, normalize_title


class _UnionFind:
    def __init__(self, n: int):
        self.parent = list(range(n))

    def find(self, x: int) -> int:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[rb] = ra


def _compatible_year(a: int | None, b: int | None) -> bool:
    if a is None or b is None:
        return True
    return abs(a - b) <= 1


def _conflicting_strong_identifiers(a: SourceRecord, b: SourceRecord) -> bool:
    doi_a, doi_b = normalize_doi(a.doi), normalize_doi(b.doi)
    if doi_a and doi_b and doi_a != doi_b:
        return True
    if a.wos_ut and b.wos_ut and a.wos_ut.strip().upper() != b.wos_ut.strip().upper():
        return True
    sc_a = a.scopus_eid or a.scopus_id
    sc_b = b.scopus_eid or b.scopus_id
    if sc_a and sc_b and sc_a.strip().lower() != sc_b.strip().lower():
        return True
    return False


def group_records(records: list[SourceRecord]) -> list[list[SourceRecord]]:
    uf = _UnionFind(len(records))
    keyed: dict[tuple[str, str], list[int]] = defaultdict(list)

    for i, record in enumerate(records):
        doi = normalize_doi(record.doi)
        if doi:
            keyed[("doi", doi)].append(i)
        if record.wos_ut:
            keyed[("wos", record.wos_ut.strip().upper())].append(i)
        if record.scopus_eid:
            keyed[("eid", record.scopus_eid.strip().lower())].append(i)
        if record.scopus_id:
            keyed[("scopus", record.scopus_id.strip())].append(i)

    for indices in keyed.values():
        for idx in indices[1:]:
            uf.union(indices[0], idx)

    # Exact-title fallback is used only when it does not contradict DOI/WoS/Scopus IDs.
    title_index: dict[str, list[int]] = defaultdict(list)
    for i, record in enumerate(records):
        title = record.normalized_title or normalize_title(record.title)
        if title:
            title_index[title].append(i)

    for indices in title_index.values():
        for pos, a in enumerate(indices):
            for b in indices[pos + 1:]:
                if _compatible_year(records[a].year, records[b].year) and not _conflicting_strong_identifiers(records[a], records[b]):
                    uf.union(a, b)

    groups: dict[int, list[SourceRecord]] = defaultdict(list)
    for i, record in enumerate(records):
        groups[uf.find(i)].append(record)
    return list(groups.values())


def canonical_id_for(group: list[SourceRecord]) -> str:
    dois = sorted({normalize_doi(r.doi) for r in group if normalize_doi(r.doi)})
    if dois:
        return f"doi:{dois[0]}"
    wos = sorted({r.wos_ut for r in group if r.wos_ut})
    if wos:
        return f"wos:{wos[0]}"
    scopus = sorted({r.scopus_eid or r.scopus_id for r in group if (r.scopus_eid or r.scopus_id)})
    if scopus:
        return f"scopus:{scopus[0]}"
    title = next((r.normalized_title for r in group if r.normalized_title), "unknown")
    year = next((r.year for r in group if r.year is not None), 0)
    digest = hashlib.sha1(f"{title}|{year}".encode("utf-8")).hexdigest()[:16]
    return f"local:{digest}"
