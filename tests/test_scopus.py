from monverify.clients.scopus import ScopusClient, normalize_scopus_entry

def entry(i, affs=2):
    return {"dc:identifier": f"SCOPUS_ID:{100+i}","eid": f"2-s2.0-{100+i}","dc:title": f"Title {i}","prism:coverDate": "2025-01-01","prism:doi": f"10.1000/{i}","prism:publicationName": "Journal","affiliation": [{"affiliation-id": "60005828", "affilname": "Medical University Varna"}] + [{"affiliation-id": str(70000000+j), "affilname": f"Inst {j}"} for j in range(affs-1)]}

def test_scopus_normalization():
    record = normalize_scopus_entry(entry(1, affs=3)); assert record.scopus_id == "101"; assert record.scopus_eid == "2-s2.0-101"; assert record.institution_count == 3; assert record.muv_affiliation is True

class FakeResponse:
    status_code = 200; headers = {}
    def __init__(self, payload): self._payload = payload
    def raise_for_status(self): return None
    def json(self): return self._payload

class FakeSession:
    def __init__(self): self.calls = 0
    def request(self, method, url, params=None, headers=None, timeout=None):
        self.calls += 1
        if self.calls == 1: payload = {"search-results": {"opensearch:totalResults": "3", "cursor": {"@next": "abc"}, "entry": [entry(1), entry(2)]}}
        else: payload = {"search-results": {"opensearch:totalResults": "3", "cursor": {"@next": "def"}, "entry": [entry(3)]}}
        return FakeResponse(payload)

def test_scopus_cursor_pagination(tmp_path):
    session = FakeSession(); client = ScopusClient("key", cache_dir=tmp_path, session=session); pages = client.search_pages("AF-ID(60005828)", count=2, use_cache=False); assert len(pages) == 2; assert session.calls == 2

def test_scopus_abstract_normalization():
    from monverify.clients.scopus import normalize_scopus_abstract
    payload = {"abstracts-retrieval-response": {"coredata": {"dc:identifier": "SCOPUS_ID:123","eid": "2-s2.0-123","dc:title": "Abstract title","prism:coverDate": "2025-05-01","prism:doi": "10.2/test","prism:publicationName": "Journal"},"affiliation": [{"@id": "60005828", "affilname": "Medical University Varna"},{"@id": "700", "affilname": "Other University"}]}}
    record = normalize_scopus_abstract(payload); assert record.scopus_id == "123"; assert record.institution_count == 2; assert record.muv_affiliation is True
