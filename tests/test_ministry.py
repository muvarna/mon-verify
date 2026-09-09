from openpyxl import Workbook
from monverify.ministry import parse_ministry_workbook

def test_parse_ministry_workbook(tmp_path):
    path = tmp_path / "ministry.xlsx"
    wb = Workbook(); ws = wb.active; ws.title = "НО"
    ws.append([None, "ИНФОРМАЦИЯ", "Период: 2025", None])
    ws.append(["1.1. (a)", "Брой научни публикации в издания, индексирани в Scopus и/или Web of Science", 334, 968.3])
    ws.append([None, "116-14+0.1*14 в списания от категория Q1 a1=", 103.4, None])
    ws.append([None, "93-1+0.1*1 в списания от категория Q2 a2=", 92.1, None])
    ws.append([None, "в списания от категория Q3 a3=", 50, None])
    ws.append([None, "всички останали публикации в Scopus и/или Web of Science a4=", 75, None])
    wb.save(path)
    claim = parse_ministry_workbook(path)
    assert claim.publication_count == 334
    assert claim.q1_raw == 116
    assert claim.q1_over_10 == 14
    assert claim.q1_weighted == 103.4
    assert claim.q2_over_10 == 1
    assert claim.a_score == 968.3
