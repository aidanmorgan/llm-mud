"""
World Loading and Template System

Handles loading static world content from YAML files and
managing entity templates for spawning.
"""

from .loader import WorldLoader, load_world
from .templates import (
    TemplateRegistry,
    RoomTemplate,
    MobTemplate,
    ItemTemplate,
    PortalTemplate,
)
from .factory import EntityFactory

__all__ = [
    "WorldLoader",
    "load_world",
    "TemplateRegistry",
    "RoomTemplate",
    "MobTemplate",
    "ItemTemplate",
    "PortalTemplate",
    "EntityFactory",
]
