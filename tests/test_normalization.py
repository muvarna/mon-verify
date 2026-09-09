from monverify.normalization import normalize_doi, normalize_issn, normalize_quartile, normalize_title

def test_doi_normalization():
    assert normalize_doi("https://doi.org/10.1000/ABC.1") == "10.1000/abc.1"
    assert normalize_doi("DOI: 10.1000/ABC.1.") == "10.1000/abc.1"
    assert normalize_doi("10.1111") is None

def test_issn_normalization():
    assert normalize_issn("1234-567X") == "1234567X"
    assert normalize_issn("1234567x") == "1234567X"
    assert normalize_issn("n/a") is None

def test_title_and_quartile_normalization():
    assert normalize_title("Journal & Medicine") == "journal and medicine"
    assert normalize_quartile("1") == "Q1"
    assert normalize_quartile("Q3") == "Q3"
