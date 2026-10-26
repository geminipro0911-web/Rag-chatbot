"""Domain entities."""

from domain.entities.user import UserContext
from domain.entities.query_intent import QueryIntent, SubQuestion
from domain.entities.entity_link import EntityLinkResult, EntityMention

__all__ = [
    "UserContext",
    "QueryIntent",
    "SubQuestion",
    "EntityLinkResult",
    "EntityMention",
]
