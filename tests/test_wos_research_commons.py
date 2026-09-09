import json

from monverify.verification import source_records_from_wos_json


def test_research_commons_records_are_excluded_from_wos_evidence(tmp_path):
    payload = {
        "mode": "institution_discovery",
        "query": 'OG=("Medical University Varna") AND PY=2025',
        "pages": [
            {
                "Data": {
                    "Records": {
                        "records": {
                            "REC": [
                                {"UID": "RC:000001"},
                                {"UID": "WOS:000002"},
                            ]
                        }
                    }
                }
            }
        ],
    }
    path = tmp_path / "wos.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    records = source_records_from_wos_json(path)
    assert [record.wos_ut for record in records] == ["WOS:000002"]
