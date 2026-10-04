import pytest
from pydantic import ValidationError

from mosaic_common.fashion_kb import enrich_product, product_text
from mosaic_common.filters import violations
from mosaic_common.schemas import HardFilters, Product


def prod(**kw):
    base = {"parent_asin": "A1", "title": "Women's Cotton Dress", "price": 1500, "stock_qty": 3, "sizes": ["S", "M"],
            "attributes": {"category": "dress", "gender": "women"}}
    base.update(kw)
    return base


def test_hard_constraints():
    f = HardFilters(price_max=2000, size="M", categories=["dress"], gender="women")
    assert violations(prod(), f) == []
    assert violations(prod(price=2500), f) == ["price"]
    assert violations(prod(stock_qty=0), f) == ["stock"]
    assert violations(prod(sizes=["L"]), f) == ["size"]
    assert violations(prod(sizes=["Free Size"]), f) == []
    assert violations(prod(attributes={"category": "saree", "gender": "women"}), f) == ["category"]
    assert violations(prod(attributes={"category": "dress", "gender": "unisex"}), f) == []
    assert violations(prod(attributes={"category": "dress", "gender": "men"}), f) == ["gender"]


def test_product_validation():
    with pytest.raises(ValidationError):
        Product(parent_asin="bad id!", title="ok title")
    with pytest.raises(ValidationError):
        Product(parent_asin="AB1", title="ok title", price=-1)
    assert Product(parent_asin="AB1", title="ok title", features="single").features == ["single"]


def test_enrichment_ignores_operational_details():
    p = {"title": "Brand Men's Linen Shirt", "details": {"Date First Available": "June 1, 2024", "Material": "Linen", "Department": "Mens"},
         "features": ["Breathable, relaxed fit"]}
    a = enrich_product(p)
    assert "party" not in a["occasions"]          # 'Date' must not become the occasion 'date'
    assert a["category"] == "shirt" and a["gender"] == "men" and a["materials"] == ["linen"]
    assert "relaxed fit" in a["comfort_tags"] and a["breathability"] > 0.9
    assert "Date First Available" not in product_text(p)


def test_enrichment_training_is_not_rain():
    a = enrich_product({"title": "Unisex Training Tights", "features": ["for gym training"]})
    assert "monsoon" not in a["seasons"]
