from monverify.dedup import group_records
from monverify.models import SourceRecord


def rec(source, sid, **kwargs):
    return SourceRecord(source=source, source_id=sid, **kwargs)


def test_doi_dedup_cross_source():
    records = [rec("omega", "o1", doi="10.1000/ABC", title="One", normalized_title="one", year=2025),rec("wos", "w1", doi="10.1000/abc", wos_ut="WOS:1", title="One", normalized_title="one", year=2025)]
    groups = group_records(records)
    assert len(groups) == 1
    assert len(groups[0]) == 2


def test_exact_title_compatible_year_dedup():
    records = [rec("wos", "w1", title="A Study", normalized_title="a study", year=2025),rec("scopus", "s1", title="A Study", normalized_title="a study", year=2026)]
    assert len(group_records(records)) == 1


def test_different_title_not_fuzzy_merged():
    records = [rec("wos", "w1", title="A Study", normalized_title="a study", year=2025),rec("scopus", "s1", title="A Studies", normalized_title="a studies", year=2025)]
    assert len(group_records(records)) == 2


def test_exact_title_does_not_merge_conflicting_dois():
    records = [rec("omega", "o1", doi="10.1000/one", wos_ut="WOS:1", title="Same Title", normalized_title="same title", year=2025),rec("omega", "o2", doi="10.1000/two", wos_ut="WOS:2", title="Same Title", normalized_title="same title", year=2025)]
    assert len(group_records(records)) == 2
