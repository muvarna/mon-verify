from monverify.clients.wos import (
    WOSClient,
    extract_wos_muv_authors,
    is_research_commons_uid,
    normalize_wos_record,
    wos_records_from_payload,
)


def sample_record(org_count=11):
    return {
        "UID": "WOS:0001",
        "static_data": {
            "summary": {
                "titles": {
                    "title": [
                        {"type": "item", "content": "Test title"},
                        {"type": "source", "content": "Test Journal"},
                    ]
                },
                "pub_info": {"pubyear": 2025},
                "doctypes": {"doctype": ["Article"]},
            },
            "fullrecord_metadata": {
                "addresses": {
                    "address_name": [
                        {
                            "address_spec": {
                                "organizations": {
                                    "organization": [
                                        {"pref": "Y", "content": "Medical University Varna"}
                                    ]
                                    + [
                                        {"pref": "Y", "content": f"Institution {i}"}
                                        for i in range(1, org_count)
                                    ]
                                }
                            }
                        }
                    ]
                }
            },
        },
        "dynamic_data": {
            "cluster_related": {
                "identifiers": {
                    "identifier": [{"type": "doi", "value": "10.1000/test"}]
                }
            }
        },
    }


def author_address_record():
    record = sample_record(2)
    record["static_data"]["summary"]["names"] = {
        "name": [
            {"role": "author", "display_name": "Smith, A.", "addr_no": "1"},
            {"role": "author", "display_name": "Jones, B.", "addr_no": "2"},
            {"role": "author", "display_name": "Both, C.", "addr_no": "1 2"},
        ]
    }
    record["static_data"]["fullrecord_metadata"]["addresses"]["address_name"] = [
        {
            "address_spec": {
                "addr_no": "1",
                "organizations": {
                    "organization": [{"pref": "Y", "content": "Medical University-Varna"}]
                },
            }
        },
        {
            "address_spec": {
                "addr_no": "2",
                "organizations": {
                    "organization": [{"pref": "Y", "content": "Other University"}]
                },
            }
        },
    ]
    return record


def test_wos_normalization_and_institution_count():
    record = normalize_wos_record(sample_record(11))
    assert record.wos_ut == "WOS:0001"
    assert record.doi == "10.1000/test"
    assert record.institution_count == 11
    assert record.muv_affiliation is True


def test_wos_muvarna_authors_follow_address_numbers():
    record = author_address_record()
    authors = extract_wos_muv_authors(record)
    assert authors == ["Smith, A.", "Both, C."]
    normalized = normalize_wos_record(record)
    assert normalized.muv_authors == ["Smith, A.", "Both, C."]


def test_research_commons_prefix_detection():
    assert is_research_commons_uid("RC:123456") is True
    assert is_research_commons_uid("rc000123") is True
    assert is_research_commons_uid("WOS:000123") is False


def test_records_from_payload():
    payload = {"Data": {"Records": {"records": {"REC": [sample_record(2)]}}}}
    assert len(wos_records_from_payload(payload)) == 1


class FakeResponse:
    status_code = 200
    headers = {}

    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self):
        self.calls = []

    def request(self, method, url, params=None, headers=None, timeout=None):
        self.calls.append(dict(params or {}))
        first = params["firstRecord"]
        total = 3
        recs = [sample_record(2)] if first == 3 else [sample_record(2), sample_record(2)]
        for i, r in enumerate(recs):
            r["UID"] = f"WOS:{first+i}"
        return FakeResponse(
            {"QueryResult": {"RecordsFound": total}, "Data": {"Records": {"records": {"REC": recs}}}}
        )


def test_wos_pagination(tmp_path):
    session = FakeSession()
    client = WOSClient("key", cache_dir=tmp_path, session=session)
    pages = client.search_pages("OG=(x)", count=2, use_cache=False)
    assert len(pages) == 2
    assert [x["firstRecord"] for x in session.calls] == [1, 3]
