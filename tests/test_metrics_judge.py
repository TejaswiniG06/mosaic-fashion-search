from evaluation.judge import grade
from evaluation.metrics import all_metrics, ndcg_at, paired_permutation_test


def T(**kw):
    t = {"parent_asin": "A", "category": "dress", "gender": "women", "material": "cotton", "colour": "navy", "pattern": "solid",
         "occasions": ["casual"], "seasons": ["summer"], "climates": ["hot", "hot_humid"], "comfort": True, "sustainable": False,
         "price": 999.0, "sizes": ["M"], "in_stock": True}
    t.update(kw)
    return t


def test_grading():
    need = {"req": {"category": ["dress"], "max_price": 2000}, "pref": {"material": ["cotton"], "climate": "hot_humid", "colour": ["blue"]}}
    assert grade(T(), need) == 3                   # navy counts as blue family
    assert grade(T(material="silk"), need) == 2
    assert grade(T(material="silk", colour="red"), need) == 1
    assert grade(T(price=2500), need) == 0
    assert grade(T(in_stock=False), need) == 0


def test_metrics():
    grades = {"a": 3, "b": 2, "c": 1}
    m = all_metrics(["a", "x", "b"], grades, [True, False, True])
    assert m["P@5"] == 2 / 5 and m["MRR"] == 1.0 and m["R@10"] == 1.0 and m["HitRate@10"] == 1.0
    assert abs(m["ConstraintSat@10"] - 2 / 3) < 1e-9
    assert ndcg_at(["a", "b", "c"], grades) == 1.0
    assert paired_permutation_test([1, 1, 1, 1, 1, 1], [0, 0, 0, 0, 0, 0], iters=2000) < 0.05
