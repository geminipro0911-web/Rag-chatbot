"""
Entity Link Domain Entities.
Represents entity mentions extracted from user queries and their linked canonical database values.
"""

from typing import Optional
from pydantic import BaseModel, Field


class EntityMention(BaseModel):
    """An entity mention extracted from a user question."""
    mention: str = Field(..., description="Exact mention string from query, e.g. 'HN', 'quý 1'")
    column: Optional[str] = Field(None, description="Candidate column name or alias, e.g. 'chi_nhanh', 'quy'")


class EntityLinkResult(BaseModel):
    """Result of linking an entity mention to a database table column and canonical value."""
    mention: str = Field(..., description="The original entity mention from the query")
    table_id: str = Field(..., description="Target table ID containing the canonical value")
    column: str = Field(..., description="Column name containing the canonical value")
    value: str = Field(..., description="Canonical value in the database")
    method: str = Field(..., description="Resolution method: 'alias' | 'fuzzy' | 'llm' | 'unlinked'")
    score: float = Field(..., ge=0.0, le=1.0, description="Matching confidence score (0.0 - 1.0)")
