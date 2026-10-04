import pytest

from services.intent.language import detect_language
from services.intent.rule_parser import parse, parse_budget, parse_size


@pytest.mark.parametrize("q,lang", [
    ("comfortable cotton dress for summer", "en"),
    ("சென்னை கோடைக்கு வசதியான பருத்தி உடை", "ta"),
    ("Chennai summer ku comfortable cotton dress venum", "tanglish"),
    ("शादी के लिए लाल लहंगा", "hi"),
    ("shaadi ke liye sherwani chahiye", "hinglish"),
    ("show me a premium medium size jacket", "en"),   # 'medium'/'premium' must not trigger Tanglish
])
def test_language_detection(q, lang):
    assert detect_language(q)[0] == lang


@pytest.mark.parametrize("q,lo,hi", [
    ("under 2000", None, 2000), ("below 2k", None, 2000), ("2000 kulla", None, 2000), ("size L 1500 kulla", None, 1500),
    ("2000 ரூபாய்க்குள்", None, 2000), ("2000க்குள்", None, 2000), ("2000 से कम", None, 2000), ("10k tak", None, 10000),
    ("between 500 and 1000", 500, 1000), ("above 3000", 3000, None), ("₹1,500", None, 1500), ("size 32 shirt", None, None),
])
def test_budget(q, lo, hi):
    assert parse_budget(q) == (lo, hi)


@pytest.mark.parametrize("q,size", [("size L", "L"), ("XL hoodie", "XL"), ("M size kurta", "M"), ("waist 32", "32"),
                                    ("free size dupatta", "Free Size"), ("cotton dress", None)])
def test_size(q, size):
    assert parse_size(q) == size


def test_tanglish_chennai_example():
    i = parse("Chennai summer ku comfortable cotton dress venum under 2000")
    assert i.language == "tanglish"
    assert i.category == ["dress"] and i.category_explicit
    assert i.material == ["cotton"] and i.comfort
    assert i.destination == "chennai" and i.season == "summer" and i.climate == "hot_humid"
    assert i.budget_max == 2000


def test_tamil_and_hindi_slots():
    ta = parse("கல்யாணத்துக்கு சிவப்பு பட்டு புடவை")
    assert (ta.category, ta.occasion, ta.material, ta.colour) == (["saree"], ["wedding"], ["silk"], ["red"])
    hi = parse("चेन्नई की गर्मी के लिए आरामदायक सूती ड्रेस 2000 से कम")
    assert hi.climate == "hot_humid" and hi.material == ["cotton"] and hi.comfort and hi.budget_max == 2000


def test_no_category_means_no_hard_category_filter():
    i = parse("I need an outfit to go to the beach this summer")
    assert i.category == [] and not i.category_explicit
    assert "beach" in i.occasion and i.climate is not None


def test_longest_match_consumes_span():
    i = parse("formal shoes for interview")
    assert i.category == ["formal-shoes"]   # not also 'sneakers' from 'shoes'
    assert i.occasion == ["office"]


def test_delhi_season_dependent_climate():
    assert parse("Delhi winter office wear").climate == "cold"
    assert parse("Delhi summer kurta").climate == "hot_dry"
