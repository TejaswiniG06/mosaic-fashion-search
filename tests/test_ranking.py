from mosaic_common.schemas import Candidate, HardFilters, Intent
from services.ranking import adaptive, explain, signals
from services.intent.rule_parser import parse


def test_weights_adapt_to_chennai_summer():
    i = parse("Chennai summer ku comfortable cotton dress venum under 2000")
    w, why = adaptive.adaptive_weights(i, visual_available=True)
    base = adaptive.fixed_weights()[0]
    for k in ("climate", "material", "comfort"):
        assert w[k] > base[k], k
    assert w["occasion"] == 0.0           # no occasion evidence
    assert abs(sum(w.values()) - 1) < 1e-9 and why


def test_image_query_boosts_visual():
    i = Intent(original_query="like this", has_query_image=True, visual_intent=True)
    w, _ = adaptive.adaptive_weights(i, visual_available=True)
    w_text, _ = adaptive.adaptive_weights(Intent(original_query="kurta"), visual_available=True)
    assert w["visual"] > 2 * w_text["visual"]


def test_fixed_weights_identical_for_all_queries():
    assert adaptive.fixed_weights()[0] == adaptive.fixed_weights()[0]


def test_missing_image_renormalises_per_candidate():
    w = {"semantic": 0.5, "lexical": 0.25, "visual": 0.25, "occasion": 0, "climate": 0, "material": 0, "comfort": 0}
    s_no_img, contrib, eff = adaptive.score({"semantic": 1.0, "lexical": 1.0, "visual": None}, w)
    assert s_no_img == 1.0 and "visual" not in contrib and abs(sum(eff.values()) - 1) < 1e-9


def test_climate_signal_prefers_breathable_for_hot_humid():
    i = parse("Chennai summer outfit")
    linen = {"breathability": 0.95, "warmth": 0.2, "seasons": ["summer"], "category": "shirt", "materials": ["linen"]}
    wool = {"breathability": 0.3, "warmth": 0.95, "seasons": ["winter"], "category": "sweater", "materials": ["wool"]}
    assert signals.climate_signal(i, linen) > 0.8 > 0.3 > signals.climate_signal(i, wool)


def test_inactive_signals_are_none():
    i = Intent(original_query="kurta")
    assert signals.occasion_signal(i, {}) is None and signals.climate_signal(i, {}) is None and signals.comfort_signal(i, {}) is None


def test_explanation_is_grounded_in_product_fields():
    i = parse("comfortable cotton dress for Chennai summer under 2000")
    p = {"title": "X Women's Cotton Midi Dress", "price": 999.0, "stock_qty": 5, "sizes": ["M"], "images": [],
         "attributes": {"category": "dress", "materials": ["cotton"], "breathability": 0.9, "warmth": 0.3, "comfort_tags": ["soft"], "occasions": []}}
    comps = {"semantic": 0.9, "lexical": 0.5, "climate": 0.9, "material": 1.0, "comfort": 0.8}
    contrib = {k: v * 0.2 for k, v in comps.items()}
    f = HardFilters(price_max=2000, categories=["dress"])
    text, cons = explain.template_explanation(i, p, comps, contrib, f, None)
    assert "cotton" in text and "₹999" in text and "₹2,000" in text and "Chennai" in text
    assert "silk" not in text and "wedding" not in text


def test_llm_grounding_check_rejects_invented_facts():
    facts = "A breathable cotton dress at 999."
    assert explain.grounded("A breathable cotton dress at 999.", facts)
    assert not explain.grounded("A cotton dress, now only 499!", facts)          # invented number
    assert not explain.grounded("Elegant silk dress for you.", facts)            # invented material
