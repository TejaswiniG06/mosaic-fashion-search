"""Strict, bounded contracts for untrusted model output."""
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Text = Annotated[str, Field(max_length=100)]
Slots = Annotated[list[Text], Field(max_length=10)]


class LLMIntent(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", allow_inf_nan=False)
    normalized_query_en: str = Field(default="", max_length=1000)
    category: Slots = Field(default_factory=list)
    category_explicit: bool = False
    occasion: Slots = Field(default_factory=list)
    season: Literal["summer", "winter", "monsoon"] | None = None
    destination: Text | None = None
    comfort: bool = False
    style: Slots = Field(default_factory=list)
    material: Slots = Field(default_factory=list)
    colour: Slots = Field(default_factory=list)
    pattern: Slots = Field(default_factory=list)
    budget_min: float | None = Field(default=None, ge=0)
    budget_max: float | None = Field(default=None, ge=0)
    size: Text | None = None
    gender: Literal["men", "women", "kids"] | None = None
    sustainability: bool = False
    brand: Slots = Field(default_factory=list)

    @model_validator(mode="after")
    def valid_budget(self):
        if self.budget_min is not None and self.budget_max is not None and self.budget_min > self.budget_max:
            raise ValueError("invalid budget range")
        return self


def validate_intent(raw: object) -> dict:
    return LLMIntent.model_validate(raw).model_dump()
