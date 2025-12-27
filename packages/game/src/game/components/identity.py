"""
Identity Components

Define how entities are named, described, and identified.
"""

from dataclasses import dataclass, field
from typing import List, Optional
from datetime import datetime

from core import ComponentData


@dataclass
class IdentityData(ComponentData):
    """
    Core identity for all entities.

    This is the basic "what is this thing" component that most
    entities will have.
    """

    name: str = "unknown"
    keywords: List[str] = field(default_factory=list)
    short_description: str = ""
    long_description: str = ""
    article: str = "a"  # "a", "an", "the", ""

    def matches_keyword(self, keyword: str) -> bool:
        """Check if a keyword matches this entity."""
        keyword = keyword.lower()
        if keyword in self.name.lower():
            return True
        return any(keyword in kw.lower() for kw in self.keywords)

    def get_short_name(self) -> str:
        """Get the name with article for display."""
        if self.article:
            return f"{self.article} {self.name}"
        return self.name


@dataclass
class StaticIdentityData(IdentityData):
    """
    Identity for static (template-defined) entities.

    These entities are loaded from YAML files and respawn
    when killed/removed.
    """

    template_id: str = ""
    zone_id: str = ""
    vnum: int = 0  # ROM-style virtual number


@dataclass
class DynamicIdentityData(IdentityData):
    """
    Identity for LLM-generated entities.

    These entities are created dynamically and may expire.
    """

    source_template_id: Optional[str] = None  # If spawned from template
    generation_context: str = ""  # LLM prompt/context that created this
    theme_id: str = ""  # Theme used for generation
    created_at: datetime = field(default_factory=datetime.utcnow)
    expires_at: Optional[datetime] = None  # For temporary entities

    def is_expired(self) -> bool:
        """Check if this dynamic entity has expired."""
        if self.expires_at is None:
            return False
        return datetime.utcnow() > self.expires_at
