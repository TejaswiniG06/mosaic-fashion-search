"""Pydantic contracts shared by all services (the API surface between microservices)."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

Language = Literal["en", "ta", "tanglish", "hi", "hinglish", "unknown"]
SearchMode = Literal["bm25", "dense", "hybrid", "mosaic"]
SIGNALS = ("semantic", "lexical", "visual", "occasion", "climate", "material", "comfort")


# --------------------------------------------------------------------------- catalogue
class ProductImage(BaseModel):
    large: str | None = None
    thumb: str | None = None
    hi_res: str | None = None
    variant: str | None = "MAIN"


class Product(BaseModel):
    """Amazon Reviews 2023 item-metadata schema + operational fields needed for commerce.

    Fields taken 1:1 from Amazon-2023 `meta_*.jsonl`: main_category, title, average_rating,
    rating_number, features, description, price, images, store, categories, details, parent_asin.
    Operational extensions: stock_qty, sizes, currency, attributes (derived, filled by enrichment).
    """

    parent_asin: str = Field(min_length=3, max_length=40, pattern=r"^[A-Za-z0-9_\-]+$")
    title: str = Field(min_length=3, max_length=500)
    main_category: str | None = "AMAZON FASHION"
    store: str | None = None
    average_rating: float | None = Field(default=None, ge=0, le=5)
    rating_number: int | None = Field(default=None, ge=0)
    features: list[str] = Field(default_factory=list)
    description: list[str] = Field(default_factory=list)
    price: float | None = Field(default=None, ge=0)
    currency: str = "INR"
    images: list[ProductImage] = Field(default_factory=list)
    categories: list[str] = Field(default_factory=list)
    details: dict[str, Any] = Field(default_factory=dict)
    stock_qty: int = Field(default=0, ge=0)
    sizes: list[str] = Field(default_factory=list)
    attributes: dict[str, Any] = Field(default_factory=dict)  # derived by enrichment; not user-supplied truth
    url: str | None = None  # product page (e.g. https://www.amazon.com/dp/<ASIN> for real Amazon data); None for synthetic items

    @field_validator("features", "description", mode="before")
    @classmethod
    def _listify(cls, v):
        if v is None:
            return []
        if isinstance(v, str):
            return [v]
        return v

    @property
    def in_stock(self) -> bool:
        return self.stock_qty > 0


class ProductPatch(BaseModel):
    title: str | None = None
    store: str | None = None
    features: list[str] | None = None
    description: list[str] | None = None
    price: float | None = Field(default=None, ge=0)
    images: list[ProductImage] | None = None
    categories: list[str] | None = None
    details: dict[str, Any] | None = None
    stock_qty: int | None = Field(default=None, ge=0)
    sizes: list[str] | None = None
    average_rating: float | None = Field(default=None, ge=0, le=5)


class CatalogueEvent(BaseModel):
    event_id: str
    type: Literal["product.upserted", "product.deleted"]
    parent_asin: str
    version: int
    ts: float
    product: dict[str, Any] | None = None


# --------------------------------------------------------------------------- intent
class Intent(BaseModel):
    original_query: str
    language: Language = "unknown"
    language_confidence: float = 0.0
    normalized_query_en: str = ""          # English canonical rewrite used by BM25 / CLIP text tower
    category: list[str] = Field(default_factory=list)
    category_explicit: bool = False        # explicit category => hard constraint
    occasion: list[str] = Field(default_factory=list)
    season: str | None = None
    climate: str | None = None             # hot_humid | hot_dry | cold | rainy | mild
    destination: str | None = None
    comfort: bool = False
    style: list[str] = Field(default_factory=list)
    material: list[str] = Field(default_factory=list)
    colour: list[str] = Field(default_factory=list)
    pattern: list[str] = Field(default_factory=list)
    budget_min: float | None = None
    budget_max: float | None = None
    size: str | None = None
    gender: str | None = None              # men | women | unisex | kids
    sustainability: bool = False
    brand: list[str] = Field(default_factory=list)
    visual_intent: bool = False            # colour/pattern/"looks like" query or query image supplied
    has_query_image: bool = False
    parser: Literal["llm", "rules", "llm+rules", "passthrough"] = "rules"
    confidence: float = 0.0
    warnings: list[str] = Field(default_factory=list)


class IntentRequest(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    has_query_image: bool = False
    use_llm: bool = True


# --------------------------------------------------------------------------- retrieval
class HardFilters(BaseModel):
    price_min: float | None = None
    price_max: float | None = None
    in_stock_only: bool = True
    size: str | None = None
    categories: list[str] = Field(default_factory=list)
    gender: str | None = None  # products tagged unisex always pass a gendered filter

    def describe(self) -> list[str]:
        out = []
        if self.price_max is not None:
            out.append(f"price <= {self.price_max:g}")
        if self.price_min is not None:
            out.append(f"price >= {self.price_min:g}")
        if self.in_stock_only:
            out.append("in stock")
        if self.size:
            out.append(f"size {self.size} available")
        if self.categories:
            out.append("category in [" + ", ".join(self.categories) + "]")
        if self.gender:
            out.append(f"gender {self.gender} (or unisex)")
        return out


class RetrieveRequest(BaseModel):
    query_text: str = ""                      # used by BM25
    text_vector: list[float] | None = None    # e5 query vector
    image_query_vector: list[float] | None = None  # CLIP image vector of an uploaded query image
    clip_text_vector: list[float] | None = None    # CLIP text vector, used to score visual similarity
    filters: HardFilters = Field(default_factory=HardFilters)
    mode: Literal["bm25", "dense", "hybrid"] = "hybrid"
    pool: int = Field(default=100, ge=1, le=1000)
    complete_signals: bool = True  # compute every signal for every candidate (needed by the MOSAIC reranker only)


class Candidate(BaseModel):
    parent_asin: str
    bm25: float = 0.0
    bm25_rank: int | None = None
    dense: float = 0.0
    dense_rank: int | None = None
    image_dense: float = 0.0
    rrf: float = 0.0
    visual: float | None = None   # CLIP cosine(query, product image); None => no image
    product: dict[str, Any] = Field(default_factory=dict)


class RetrieveResponse(BaseModel):
    candidates: list[Candidate]
    mode_used: str
    degraded: list[str] = Field(default_factory=list)
    timings_ms: dict[str, float] = Field(default_factory=dict)
    filtered_out: dict[str, int] = Field(default_factory=dict)
    index_size: int = 0


# --------------------------------------------------------------------------- ranking
class RankOptions(BaseModel):
    adaptive: bool = True
    use_visual: bool = True
    use_context: bool = True     # occasion/climate/material/comfort signals
    explain: bool = True
    top_k: int = Field(default=10, ge=1, le=100)
    base_mode: SearchMode = "mosaic"


class RankRequest(BaseModel):
    intent: Intent
    candidates: list[Candidate]
    filters: HardFilters
    options: RankOptions = Field(default_factory=RankOptions)


class ScoredProduct(BaseModel):
    rank: int
    parent_asin: str
    title: str
    score: float
    components: dict[str, float]            # raw signal values in [0,1]
    contributions: dict[str, float]         # weight * signal
    price: float | None = None
    store: str | None = None
    image: str | None = None
    has_image: bool = False
    in_stock: bool = True
    sizes: list[str] = Field(default_factory=list)
    attributes: dict[str, Any] = Field(default_factory=dict)
    constraints_satisfied: list[str] = Field(default_factory=list)
    explanation: str = ""
    explanation_source: Literal["template", "llm", "none"] = "none"
    url: str | None = None
    rating: float | None = None


class RankResponse(BaseModel):
    results: list[ScoredProduct]
    weights: dict[str, float]
    weight_rationale: list[str]
    timings_ms: dict[str, float] = Field(default_factory=dict)


# --------------------------------------------------------------------------- gateway
class Ablation(BaseModel):
    adaptive: bool = True
    use_visual: bool = True
    use_intent: bool = True
    use_context: bool = True
    retrieval: Literal["hybrid", "dense"] = "hybrid"   # candidate generation used by MOSAIC


class SearchRequest(BaseModel):
    query: str = Field(default="", max_length=500)
    image_b64: str | None = None
    mode: SearchMode = "mosaic"
    top_k: int = Field(default=10, ge=1, le=50)
    explain: bool = True
    use_llm: bool = True
    ablation: Ablation = Field(default_factory=Ablation)
    use_cache: bool = True
    relax: list[Literal["price", "size", "category", "gender"]] = Field(default_factory=list)  # user chose to drop these constraints
    budget_max_override: float | None = Field(default=None, ge=0)


class Suggestion(BaseModel):
    """'No results' helper: a single-constraint relaxation that would return products."""
    relax: Literal["price", "size", "category", "gender"]
    label: str
    matches: int
    budget_max_override: float | None = None


class Feedback(BaseModel):
    request_id: str = Field(max_length=64)
    query: str = Field(max_length=500)
    parent_asin: str = Field(max_length=40)
    rank: int = Field(ge=1, le=100)
    vote: Literal["up", "down"]
    mode: str = "mosaic"
    score: float | None = None
    components: dict[str, float] = Field(default_factory=dict)


class SearchResponse(BaseModel):
    request_id: str
    query: str
    mode: SearchMode
    intent: Intent | None
    filters: HardFilters
    constraints_applied: list[str]
    retrieval_mode: str
    weights: dict[str, float] = Field(default_factory=dict)
    weight_rationale: list[str] = Field(default_factory=list)
    results: list[ScoredProduct]
    degraded: list[str] = Field(default_factory=list)
    timings_ms: dict[str, float] = Field(default_factory=dict)
    filtered_out: dict[str, int] = Field(default_factory=dict)
    index_size: int = 0
    cached: bool = False
    catalogue_version: int = 0
    suggestions: list[Suggestion] = Field(default_factory=list)
