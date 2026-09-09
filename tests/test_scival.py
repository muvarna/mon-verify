from pathlib import Path

from monverify.scival import inspect_scival, load_scival_counts


def _write_scival(path: Path) -> None:
    path.write_text(
        'Data set,"Publications at the Medical University of Varna"\n'
        'Year range,2025\n'
        'Subject classification,"ASJC"\n'
        'Filtered by,"not filtered"\n'
        'Types of publications included,"All publication types"\n'
        'Self-citations,-\n\n'
        'Data source,Scopus\n'
        'Date last updated,6 September 2026\n'
        'Date exported,9 September 2026\n\n'
        '2 publications\n\n'
        'Truncated fields,Some Authors cells are truncated.\n\n'
        '"Title","Authors","Year","Scopus Source title","ISSN","Language","DOI","Publication type","EID","Number of Institutions"\n'
        '"Paper A","A, A.","2025","Journal A","ISSN-12345678","English","10.1000/ABC","Article","2-s2.0-12345","11"\n'
        '"Paper B","B, B.","2025","Journal B","ISSN-87654321","English","-","Review","2-s2.0-67890","2"\n'
        '"© 2026 Elsevier B.V. All rights reserved.","","","","","","","","",""\n',
        encoding="utf-8",
    )


def test_scival_preamble_and_standard_columns_are_auto_detected(tmp_path: Path) -> None:
    path = tmp_path / "scival.csv"
    _write_scival(path)
    lookup = load_scival_counts(path)

    assert lookup[("scopus", "2-s2.0-12345")] == 11
    assert lookup[("scopus", "12345")] == 11
    assert lookup[("doi", "10.1000/abc")] == 11
    assert lookup[("title_year", "paper a|2025")] == 11


def test_inspect_scival_ignores_footer(tmp_path: Path) -> None:
    path = tmp_path / "scival.csv"
    _write_scival(path)
    result = inspect_scival(path)

    assert result["rows"] == 2
    assert result["over_10_institutions"] == 1
    assert result["max_institutions"] == 11
