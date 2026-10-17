"""Pydantic request/response models."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

ID_RE = r"^[A-Z]{1,3}-[A-Z0-9-]{2,20}$"


class InvestigateRequest(BaseModel):
    question: str | None = Field(default=None, max_length=500)
    retailer_id: str | None = Field(default=None, pattern=r"^R-\d{3}$")
    product_id: str | None = Field(default=None, pattern=r"^P-\d{2}$")
    scenario_id: str | None = Field(default=None, pattern=r"^[A-Z]$")

    @field_validator("question")
    @classmethod
    def strip_question(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = " ".join(v.split())
        return v or None

    @model_validator(mode="after")
    def need_something(self):
        if not (self.question or self.scenario_id or (self.retailer_id and self.product_id)):
            raise ValueError("Provide a question, a scenario_id, or both retailer_id and product_id.")
        return self


class MutationRequest(BaseModel):
    entity_type: Literal["Delivery", "Inventory"]
    record_id: str = Field(pattern=ID_RE, max_length=32)
    field: Literal["status", "quantity", "reserved_quantity"]
    value: Any
    confirm: bool = Field(default=False, description="Must be true to change the demo dataset")


class ErrorBody(BaseModel):
    code: str
    message: str
    details: dict | None = None


class ProbableCause(BaseModel):
    code: str
    label: str
    status: Literal["supported", "hypothesis", "record_gap", "undetermined", "not_applicable"]
    status_meaning: str
    confidence: Literal["high", "medium", "low"]
    confidence_basis: str


class InvestigationResponse(BaseModel):
    investigation_id: str
    generated_at: str
    demo_clock: str
    data_mode: Literal["simulated"] = "simulated"
    question: str | None
    intent: str
    resolved_by: str
    scenario_id: str | None
    retailer: dict
    product: dict
    summary: str
    summary_source: Literal["deterministic", "llm"]
    summary_note: str | None = None
    probable_cause: ProbableCause
    stock_summary: dict
    observed_facts: list[dict]
    inferences: list[dict]
    missing_information: list[dict]
    contradictions: list[dict]
    evidence: list[dict]
    graph: dict
    graph_path: list[dict]
    recommended_actions: list[dict]
    hypothesis_tests: dict
    query_trace: list[dict]
