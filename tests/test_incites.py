import pandas as pd
from monverify.incites import QuartileIndex

def test_match_priority_and_fuzzy_review():
    frame = pd.DataFrame([{"Name": "Exact Journal", "ISSN": "1234-5678", "eISSN": "", "Journal Impact Factor": "5.0", "JIF Quartile": "Q1"},{"Name": "Another Journal", "ISSN": "", "eISSN": "8765-4321", "Journal Impact Factor": "2.0", "JIF Quartile": "Q3"}])
    index = QuartileIndex(frame)
    match = index.match("1234-5678", None, "Wrong title")
    assert match.quartile == "Q1"
    assert match.method == "issn"
    fuzzy = index.match(None, None, "Exact Journl", fuzzy_threshold=80)
    assert fuzzy.quartile is None
    assert fuzzy.method == "title_fuzzy"
    assert fuzzy.confidence == "manual_review"
