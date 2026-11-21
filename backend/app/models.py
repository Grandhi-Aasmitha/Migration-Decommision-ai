from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

DocumentType = Literal["source_app", "target", "policy", "nfr"]
Relation = Literal["DEPENDS_ON", "HAS_CAPABILITY", "MUST_MEET"]


class Fact(BaseModel):
    model_config = ConfigDict(extra="forbid")
    relation: Relation
    name: str = Field(min_length=1, max_length=160)
    quote: str = Field(min_length=3, max_length=1500)


class Extraction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    facts: list[Fact] = Field(default_factory=list, max_length=50)


class ChatRequest(BaseModel):
    question: str = Field(min_length=3, max_length=2000)
    application_id: str = Field(min_length=1, max_length=100)
    document_types: list[DocumentType] = Field(
        default_factory=lambda: ["source_app", "target", "policy", "nfr"], min_length=1
    )
    top_k: int = Field(default=6, ge=1, le=15)

    @field_validator("question", "application_id")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Must not be blank")
        return value.strip()


class AssessmentRequest(BaseModel):
    application_id: str = Field(min_length=1, max_length=100)
    target_ids: list[str] = Field(default_factory=list, max_length=5)
    objective: Literal["balanced", "capabilities", "integrations"] | None = None


class ClarificationAnswer(BaseModel):
    objective: Literal["balanced", "capabilities", "integrations"]
