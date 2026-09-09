from pathlib import Path
from monverify.omega import omega_records, parse_journal_field

def test_parse_journal_field():
    title, issn, eissn = parse_journal_field("Example Journal, ISSN 1234-5678, e-ISSN 8765-4321, Monthly")
    assert title == "Example Journal"; assert issn == "12345678"; assert eissn == "87654321"

def test_scopus_id_kept_as_text(tmp_path: Path):
    path = tmp_path / "omega.csv"
    path.write_text("Reference,Journal,publicationType,Issue year,DOI,WoSId,ScopusId,JIFQuartile, Authors MU-Varna,Link WOS,Link Scopus\n" '"A A : Test title, Test Journal, 2025","Test Journal, ISSN 1234-5678",article,2025,10.1000/test,WOS:1,105001036246,1,A A,,\n', encoding="utf-8")
    record = omega_records(path)[0]
    assert record.scopus_id == "105001036246"
    assert record.title == "Test title"
