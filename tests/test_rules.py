from monverify.rules import RuleEngine

def test_ministry_fixture():
    rules = RuleEngine.from_yaml("config/rules_2025.yaml")
    q1 = 116 - 14 + 14 * 0.1; q2 = 93 - 1 + 1 * 0.1
    weighted = {"a1": q1, "a2": q2, "a3": 50.0, "a4": 75.0}
    assert q1 == 103.4; assert q2 == 92.1; assert rules.score(weighted) == 968.3

def test_institution_boundary():
    rules = RuleEngine.from_yaml("config/rules_2025.yaml")
    assert rules.multiplier(None) is None; assert rules.is_over_threshold(10) is False; assert rules.multiplier(10) == 1.0; assert rules.is_over_threshold(11) is True; assert rules.multiplier(11) == 0.1
