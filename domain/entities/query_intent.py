"""
Query Intent Domain Entity.
Structured output schema for Router classification.
"""

from typing import List, Optional
from pydantic import BaseModel, Field


class SubQuestion(BaseModel):
    q: str = Field(..., description="Sub-question query text")
    engine: str = Field(..., description="Target engine: 'TABULAR' or 'DOCUMENT'")


class QueryIntent(BaseModel):
    route: str = Field(
        ...,
        description="Target route: 'TABULAR' | 'DOCUMENT' | 'HYBRID' | 'CLARIFY' | 'CHITCHAT' | 'OUT_OF_SCOPE'"
    )
    confidence: float = Field(..., ge=0.0, le=1.0, description="Routing confidence score")
    candidate_table_ids: List[str] = Field(default_factory=list, description="List of relevant table IDs")
    candidate_doc_ids: List[str] = Field(default_factory=list, description="List of relevant document IDs")
    sub_questions: List[SubQuestion] = Field(
        default_factory=list,
        description="Sub-questions when route is HYBRID"
    )
    clarify_question: Optional[str] = Field(
        default=None,
        description="Clarification question when route is CLARIFY"
    )
    reason: str = Field(..., max_length=255, description="Short justification (<= 1 sentence)")
