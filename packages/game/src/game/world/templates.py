"""
Template Definitions and Registry

Templates define the "blueprints" for static entities that can be
spawned in the world. They're loaded from YAML files.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
import logging

from ..components.spatial import SectorType, WorldCoordinate, Direction
from ..components.combat import DamageType
from ..components.ai import BehaviorType, CombatStyle
from ..components.inventory import (
    ItemType,
    ItemRarity,
    WeaponType,
    ArmorType,
    EquipmentSlot,
    ConsumableEffectType,
)

logger = logging.getLogger(__name__)


@dataclass
class RoomTemplate:
    """Template for a static room."""

    template_id: str
    zone_id: str = ""
    vnum: int = 0

    # Descriptions
    name: str = "A Room"
    short_description: str = "A room"
    long_description: str = "You see nothing special."

    # Exits: direction -> destination template_id
    exits: Dict[str, str] = field(default_factory=dict)

    # Properties
    sector_type: SectorType = SectorType.INSIDE
    flags: List[str] = field(default_factory=list)

    # Ambient
    ambient_messages: List[str] = field(default_factory=list)

    # Spawns
    mob_spawns: List[Dict[str, Any]] = field(default_factory=list)
    item_spawns: List[Dict[str, Any]] = field(default_factory=list)

    # Reset
    respawn_interval_s: int = 300


@dataclass
class MobTemplate:
    """Template for a static mob."""

    template_id: str
    zone_id: str = ""
    vnum: int = 0

    # Identity
    name: str = "a creature"
    keywords: List[str] = field(default_factory=list)
    short_description: str = "A creature is here."
    long_description: str = "You see nothing special."

    # Stats
    level: int = 1
    health: int = 100
    mana: int = 50

    # Attributes
    strength: int = 10
    dexterity: int = 10
    constitution: int = 10
    intelligence: int = 10
    wisdom: int = 10
    charisma: int = 10

    # Combat
    damage_dice: str = "1d6"
    damage_type: DamageType = DamageType.BLUDGEONING
    armor_class: int = 10
    attack_bonus: int = 0

    # Behavior
    behavior_type: BehaviorType = BehaviorType.PASSIVE
    combat_style: CombatStyle = CombatStyle.TACTICIAN
    aggro_radius: int = 0
    flee_threshold: float = 0.2

    # Loot
    gold_min: int = 0
    gold_max: int = 10
    loot_table: List[Dict[str, Any]] = field(default_factory=list)

    # Experience
    experience_value: int = 100

    # Flags
    flags: List[str] = field(default_factory=list)

    # Dialogue
    dialogue: Optional[Dict[str, str]] = None


@dataclass
class ItemTemplate:
    """Template for an item."""

    template_id: str
    zone_id: str = ""
    vnum: int = 0

    # Identity
    name: str = "an item"
    keywords: List[str] = field(default_factory=list)
    short_description: str = "An item is here."
    long_description: str = "You see nothing special."

    # Type
    item_type: ItemType = ItemType.MISC
    rarity: ItemRarity = ItemRarity.COMMON

    # Properties
    weight: float = 1.0
    value: int = 0
    level_requirement: int = 0

    # Weapon properties (if weapon)
    damage_dice: Optional[str] = None
    damage_type: Optional[DamageType] = None
    weapon_type: Optional[WeaponType] = None
    two_handed: bool = False
    hit_bonus: int = 0
    damage_bonus: int = 0

    # Armor properties (if armor)
    armor_bonus: int = 0
    armor_type: Optional[ArmorType] = None
    equipment_slot: Optional[EquipmentSlot] = None

    # Consumable properties
    effect_type: Optional[ConsumableEffectType] = None
    effect_value: int = 0
    uses: int = 1

    # Flags
    flags: List[str] = field(default_factory=list)


@dataclass
class PortalTemplate:
    """Template for a portal to dynamic content."""

    template_id: str
    zone_id: str = ""

    # Identity
    name: str = "a portal"
    keywords: List[str] = field(default_factory=list)
    description: str = "A shimmering portal."

    # Theme
    theme_id: str = ""
    theme_description: str = ""

    # Instance settings
    instance_type: str = "dungeon"
    difficulty_min: int = 1
    difficulty_max: int = 10
    max_rooms: int = 15
    max_players: int = 8

    # Requirements
    min_level: int = 1
    required_items: List[str] = field(default_factory=list)

    # Cooldown
    cooldown_s: int = 3600


@dataclass
class RegionThemeTemplate:
    """
    Theme configuration for dynamic region generation.

    All LLM prompts are loaded from YAML configuration.
    """

    theme_id: str
    description: str = ""

    # LLM prompt templates with {placeholders}
    room_prompt: str = ""
    mob_prompt: str = ""
    item_prompt: str = ""

    # Vocabulary constraints
    vocabulary: List[str] = field(default_factory=list)
    forbidden_words: List[str] = field(default_factory=list)

    # Terrain constraints
    sector_types: List[SectorType] = field(default_factory=list)

    # Fallback templates if LLM unavailable
    mob_templates: List[str] = field(default_factory=list)
    item_templates: List[str] = field(default_factory=list)

    # Ambient messages
    ambient_messages: List[str] = field(default_factory=list)


@dataclass
class RegionEndpointTemplate:
    """Connection point between a dynamic region and a static room."""

    static_room_id: str
    direction: Direction
    coordinate: WorldCoordinate


@dataclass
class RegionWaypointTemplate:
    """Optional waypoint for guiding region generation."""

    coordinate: WorldCoordinate
    name: str = ""
    is_required: bool = True


@dataclass
class RegionTemplate:
    """
    Template for a dynamic region connecting static areas.

    Dynamic regions are LLM-generated transition zones between
    static areas. All configuration including prompts is in YAML.
    """

    template_id: str
    name: str = "Unnamed Region"

    # Theme with embedded LLM prompts
    theme: Optional[RegionThemeTemplate] = None

    # Connection points to static areas
    endpoints: List[RegionEndpointTemplate] = field(default_factory=list)

    # Optional waypoints for route planning
    waypoints: List[RegionWaypointTemplate] = field(default_factory=list)

    # Generation parameters
    min_rooms: int = 5
    max_rooms: int = 15
    difficulty_min: int = 1
    difficulty_max: int = 5
    mob_density: float = 0.3
    item_density: float = 0.1
    branch_chance: float = 0.2

    # Primary terrain type
    primary_sector_type: SectorType = SectorType.FOREST

    def get_endpoint_by_room(self, static_room_id: str) -> Optional[RegionEndpointTemplate]:
        """Get endpoint configuration for a static room."""
        for endpoint in self.endpoints:
            if endpoint.static_room_id == static_room_id:
                return endpoint
        return None


class TemplateRegistry:
    """
    Central registry for all templates.

    Templates can be looked up by template_id or vnum.
    """

    def __init__(self):
        self._rooms: Dict[str, RoomTemplate] = {}
        self._mobs: Dict[str, MobTemplate] = {}
        self._items: Dict[str, ItemTemplate] = {}
        self._portals: Dict[str, PortalTemplate] = {}
        self._regions: Dict[str, RegionTemplate] = {}

        # Vnum lookups
        self._room_vnums: Dict[int, str] = {}
        self._mob_vnums: Dict[int, str] = {}
        self._item_vnums: Dict[int, str] = {}

        # Static room to region mapping (which regions connect to which rooms)
        self._room_to_regions: Dict[str, List[str]] = {}

    # =========================================================================
    # Room Templates
    # =========================================================================

    def register_room(self, template: RoomTemplate) -> None:
        """Register a room template."""
        self._rooms[template.template_id] = template
        if template.vnum > 0:
            self._room_vnums[template.vnum] = template.template_id
        logger.debug(f"Registered room template: {template.template_id}")

    def get_room(self, template_id: str) -> Optional[RoomTemplate]:
        """Get room template by ID."""
        return self._rooms.get(template_id)

    def get_room_by_vnum(self, vnum: int) -> Optional[RoomTemplate]:
        """Get room template by vnum."""
        template_id = self._room_vnums.get(vnum)
        if template_id:
            return self._rooms.get(template_id)
        return None

    def get_all_rooms(self) -> Dict[str, RoomTemplate]:
        """Get all room templates."""
        return self._rooms.copy()

    def get_rooms_in_zone(self, zone_id: str) -> List[RoomTemplate]:
        """Get all rooms in a zone."""
        return [r for r in self._rooms.values() if r.zone_id == zone_id]

    # =========================================================================
    # Mob Templates
    # =========================================================================

    def register_mob(self, template: MobTemplate) -> None:
        """Register a mob template."""
        self._mobs[template.template_id] = template
        if template.vnum > 0:
            self._mob_vnums[template.vnum] = template.template_id
        logger.debug(f"Registered mob template: {template.template_id}")

    def get_mob(self, template_id: str) -> Optional[MobTemplate]:
        """Get mob template by ID."""
        return self._mobs.get(template_id)

    def get_mob_by_vnum(self, vnum: int) -> Optional[MobTemplate]:
        """Get mob template by vnum."""
        template_id = self._mob_vnums.get(vnum)
        if template_id:
            return self._mobs.get(template_id)
        return None

    def get_all_mobs(self) -> Dict[str, MobTemplate]:
        """Get all mob templates."""
        return self._mobs.copy()

    # =========================================================================
    # Item Templates
    # =========================================================================

    def register_item(self, template: ItemTemplate) -> None:
        """Register an item template."""
        self._items[template.template_id] = template
        if template.vnum > 0:
            self._item_vnums[template.vnum] = template.template_id
        logger.debug(f"Registered item template: {template.template_id}")

    def get_item(self, template_id: str) -> Optional[ItemTemplate]:
        """Get item template by ID."""
        return self._items.get(template_id)

    def get_item_by_vnum(self, vnum: int) -> Optional[ItemTemplate]:
        """Get item template by vnum."""
        template_id = self._item_vnums.get(vnum)
        if template_id:
            return self._items.get(template_id)
        return None

    def get_all_items(self) -> Dict[str, ItemTemplate]:
        """Get all item templates."""
        return self._items.copy()

    # =========================================================================
    # Portal Templates
    # =========================================================================

    def register_portal(self, template: PortalTemplate) -> None:
        """Register a portal template."""
        self._portals[template.template_id] = template
        logger.debug(f"Registered portal template: {template.template_id}")

    def get_portal(self, template_id: str) -> Optional[PortalTemplate]:
        """Get portal template by ID."""
        return self._portals.get(template_id)

    def get_all_portals(self) -> Dict[str, PortalTemplate]:
        """Get all portal templates."""
        return self._portals.copy()

    # =========================================================================
    # Region Templates
    # =========================================================================

    def register_region(self, template: RegionTemplate) -> None:
        """Register a region template."""
        self._regions[template.template_id] = template

        # Build room-to-region mapping for quick lookups
        for endpoint in template.endpoints:
            if endpoint.static_room_id not in self._room_to_regions:
                self._room_to_regions[endpoint.static_room_id] = []
            if template.template_id not in self._room_to_regions[endpoint.static_room_id]:
                self._room_to_regions[endpoint.static_room_id].append(template.template_id)

        logger.debug(f"Registered region template: {template.template_id}")

    def get_region(self, template_id: str) -> Optional[RegionTemplate]:
        """Get region template by ID."""
        return self._regions.get(template_id)

    def get_all_regions(self) -> Dict[str, RegionTemplate]:
        """Get all region templates."""
        return self._regions.copy()

    def get_regions_for_room(self, room_template_id: str) -> List[RegionTemplate]:
        """Get all regions that connect to a static room."""
        region_ids = self._room_to_regions.get(room_template_id, [])
        return [self._regions[rid] for rid in region_ids if rid in self._regions]

    def get_region_by_endpoint(
        self, room_template_id: str, direction: Direction
    ) -> Optional[RegionTemplate]:
        """Get the region that connects to a room in a specific direction."""
        for region in self.get_regions_for_room(room_template_id):
            endpoint = region.get_endpoint_by_room(room_template_id)
            if endpoint and endpoint.direction == direction:
                return region
        return None

    # =========================================================================
    # Stats
    # =========================================================================

    def get_stats(self) -> Dict[str, int]:
        """Get registry statistics."""
        return {
            "rooms": len(self._rooms),
            "mobs": len(self._mobs),
            "items": len(self._items),
            "portals": len(self._portals),
            "regions": len(self._regions),
        }


# Global registry instance
_registry: Optional[TemplateRegistry] = None


def get_template_registry() -> TemplateRegistry:
    """Get the global template registry."""
    global _registry
    if _registry is None:
        _registry = TemplateRegistry()
    return _registry
