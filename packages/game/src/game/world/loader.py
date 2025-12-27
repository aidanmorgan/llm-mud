"""
World Loader

Loads world content from YAML files into the template registry.

Supports both:
- Synchronous loading into local TemplateRegistry (legacy)
- Asynchronous loading into distributed TemplateRegistryActor
"""

import logging
from enum import Enum
from pathlib import Path
from typing import Dict, List, Any, Optional, Type, TypeVar

import yaml

from .templates import (
    TemplateRegistry,
    RoomTemplate,
    MobTemplate,
    ItemTemplate,
    PortalTemplate,
    RegionTemplate,
    RegionThemeTemplate,
    RegionEndpointTemplate,
    RegionWaypointTemplate,
    get_template_registry,
    SectorType,
    DamageType,
    BehaviorType,
    CombatStyle,
    ItemType,
    ItemRarity,
    WeaponType,
    ArmorType,
    EquipmentSlot,
    ConsumableEffectType,
)
from ..components.spatial import Direction, WorldCoordinate
from .template_actor import (
    get_template_registry_actor,
)

E = TypeVar("E", bound=Enum)

logger = logging.getLogger(__name__)


def _parse_enum(value: Optional[str], enum_class: Type[E], default: E) -> E:
    """
    Parse a string value into an enum, with fallback to default.

    Args:
        value: The string value from YAML (may be None)
        enum_class: The enum class to parse into
        default: Default value if parsing fails

    Returns:
        The parsed enum value or default
    """
    if value is None:
        return default
    try:
        return enum_class(value)
    except ValueError:
        logger.warning(f"Unknown {enum_class.__name__} value: {value}, using {default.value}")
        return default


def _parse_optional_enum(value: Optional[str], enum_class: Type[E]) -> Optional[E]:
    """
    Parse a string value into an optional enum.

    Args:
        value: The string value from YAML (may be None)
        enum_class: The enum class to parse into

    Returns:
        The parsed enum value or None
    """
    if value is None:
        return None
    try:
        return enum_class(value)
    except ValueError:
        logger.warning(f"Unknown {enum_class.__name__} value: {value}")
        return None


class WorldLoader:
    """
    Loads world data from YAML files.

    Expected directory structure:
        world/
            zones/
                zone_id.yaml      # Zone metadata
            rooms/
                area_name.yaml    # Room definitions
            mobs/
                mobs.yaml         # Mob templates
            items/
                items.yaml        # Item templates
            portals/
                portals.yaml      # Portal definitions
            regions/
                region_id.yaml    # Dynamic region definitions with LLM prompts
    """

    def __init__(self, world_path: str, registry: Optional[TemplateRegistry] = None):
        self.world_path = Path(world_path)
        self.registry = registry or get_template_registry()

        self._zones_loaded: List[str] = []
        self._errors: List[str] = []

    def load_all(self) -> Dict[str, Any]:
        """
        Load all world content.

        Returns dict with load statistics.
        """
        stats = {
            "rooms": 0,
            "mobs": 0,
            "items": 0,
            "portals": 0,
            "regions": 0,
            "zones": 0,
            "errors": [],
        }

        logger.info(f"Loading world from: {self.world_path}")

        # Load zones first
        zones_path = self.world_path / "zones"
        if zones_path.exists():
            stats["zones"] = self._load_zones(zones_path)

        # Load rooms
        rooms_path = self.world_path / "rooms"
        if rooms_path.exists():
            stats["rooms"] = self._load_rooms(rooms_path)

        # Load mobs
        mobs_path = self.world_path / "mobs"
        if mobs_path.exists():
            stats["mobs"] = self._load_mobs(mobs_path)

        # Load items
        items_path = self.world_path / "items"
        if items_path.exists():
            stats["items"] = self._load_items(items_path)

        # Load portals
        portals_path = self.world_path / "portals"
        if portals_path.exists():
            stats["portals"] = self._load_portals(portals_path)

        # Load regions
        regions_path = self.world_path / "regions"
        if regions_path.exists():
            stats["regions"] = self._load_regions(regions_path)

        stats["errors"] = self._errors.copy()

        logger.info(
            f"World loaded: {stats['rooms']} rooms, {stats['mobs']} mobs, "
            f"{stats['items']} items, {stats['portals']} portals, "
            f"{stats['regions']} regions, {len(stats['errors'])} errors"
        )

        return stats

    def _load_yaml_file(self, path: Path) -> Optional[Dict]:
        """Load and parse a YAML file."""
        try:
            with open(path, "r") as f:
                return yaml.safe_load(f)
        except Exception as e:
            self._errors.append(f"Error loading {path}: {e}")
            logger.error(f"Error loading {path}: {e}")
            return None

    def _load_zones(self, zones_path: Path) -> int:
        """Load zone metadata files."""
        count = 0
        for yaml_file in zones_path.glob("*.yaml"):
            data = self._load_yaml_file(yaml_file)
            if data:
                zone_id = yaml_file.stem
                self._zones_loaded.append(zone_id)
                count += 1
                logger.debug(f"Loaded zone: {zone_id}")
        return count

    def _load_rooms(self, rooms_path: Path) -> int:
        """Load room definition files."""
        count = 0
        for yaml_file in rooms_path.glob("*.yaml"):
            data = self._load_yaml_file(yaml_file)
            if data and "rooms" in data:
                zone_id = data.get("zone_id", yaml_file.stem)

                for room_data in data["rooms"]:
                    try:
                        template = self._parse_room(room_data, zone_id)
                        self.registry.register_room(template)
                        count += 1
                    except Exception as e:
                        self._errors.append(f"Error parsing room in {yaml_file}: {e}")
                        logger.error(f"Error parsing room: {e}")

        return count

    def _parse_room(self, data: Dict, zone_id: str) -> RoomTemplate:
        """Parse room data into template."""
        return RoomTemplate(
            template_id=data.get("id", data.get("template_id", "")),
            zone_id=zone_id,
            vnum=data.get("vnum", 0),
            name=data.get("name", "A Room"),
            short_description=data.get("short_description", data.get("name", "A room")),
            long_description=data.get("long_description", "You see nothing special."),
            exits=data.get("exits", {}),
            sector_type=_parse_enum(data.get("sector_type"), SectorType, SectorType.INSIDE),
            flags=data.get("flags", []),
            ambient_messages=data.get("ambient_messages", []),
            mob_spawns=data.get("mob_spawns", data.get("mobs", [])),
            item_spawns=data.get("item_spawns", data.get("items", [])),
            respawn_interval_s=data.get("respawn_interval_s", 300),
        )

    def _load_mobs(self, mobs_path: Path) -> int:
        """Load mob template files."""
        count = 0
        for yaml_file in mobs_path.glob("*.yaml"):
            data = self._load_yaml_file(yaml_file)
            if data and "mobs" in data:
                zone_id = data.get("zone_id", "")

                for mob_data in data["mobs"]:
                    try:
                        template = self._parse_mob(mob_data, zone_id)
                        self.registry.register_mob(template)
                        count += 1
                    except Exception as e:
                        self._errors.append(f"Error parsing mob in {yaml_file}: {e}")
                        logger.error(f"Error parsing mob: {e}")

        return count

    def _parse_mob(self, data: Dict, zone_id: str) -> MobTemplate:
        """Parse mob data into template."""
        stats = data.get("stats", {})
        behavior = data.get("behavior", {})
        loot = data.get("loot", {})

        return MobTemplate(
            template_id=data.get("id", data.get("template_id", "")),
            zone_id=zone_id,
            vnum=data.get("vnum", 0),
            name=data.get("name", "a creature"),
            keywords=data.get("keywords", []),
            short_description=data.get("short_description", ""),
            long_description=data.get("long_description", ""),
            level=data.get("level", stats.get("level", 1)),
            health=stats.get("health", stats.get("max_health", 100)),
            mana=stats.get("mana", stats.get("max_mana", 50)),
            strength=stats.get("strength", 10),
            dexterity=stats.get("dexterity", 10),
            constitution=stats.get("constitution", 10),
            intelligence=stats.get("intelligence", 10),
            wisdom=stats.get("wisdom", 10),
            charisma=stats.get("charisma", 10),
            damage_dice=data.get("damage_dice", stats.get("damage_dice", "1d6")),
            damage_type=_parse_enum(data.get("damage_type"), DamageType, DamageType.BLUDGEONING),
            armor_class=stats.get("armor_class", 10),
            attack_bonus=stats.get("attack_bonus", 0),
            behavior_type=_parse_enum(behavior.get("type"), BehaviorType, BehaviorType.PASSIVE),
            combat_style=_parse_enum(behavior.get("combat_style"), CombatStyle, CombatStyle.TACTICIAN),
            aggro_radius=behavior.get("aggro_radius", 0),
            flee_threshold=behavior.get("flee_threshold", 0.2),
            gold_min=loot.get("gold_min", 0),
            gold_max=loot.get("gold_max", 10),
            loot_table=loot.get("items", []),
            experience_value=data.get("experience", 100),
            flags=data.get("flags", []),
            dialogue=data.get("dialogue"),
        )

    def _load_items(self, items_path: Path) -> int:
        """Load item template files."""
        count = 0
        for yaml_file in items_path.glob("*.yaml"):
            data = self._load_yaml_file(yaml_file)
            if data and "items" in data:
                zone_id = data.get("zone_id", "")

                for item_data in data["items"]:
                    try:
                        template = self._parse_item(item_data, zone_id)
                        self.registry.register_item(template)
                        count += 1
                    except Exception as e:
                        self._errors.append(f"Error parsing item in {yaml_file}: {e}")
                        logger.error(f"Error parsing item: {e}")

        return count

    def _parse_item(self, data: Dict, zone_id: str) -> ItemTemplate:
        """Parse item data into template."""
        weapon = data.get("weapon", {})
        armor = data.get("armor", {})
        consumable = data.get("consumable", {})

        return ItemTemplate(
            template_id=data.get("id", data.get("template_id", "")),
            zone_id=zone_id,
            vnum=data.get("vnum", 0),
            name=data.get("name", "an item"),
            keywords=data.get("keywords", []),
            short_description=data.get("short_description", ""),
            long_description=data.get("long_description", ""),
            item_type=_parse_enum(data.get("type", data.get("item_type")), ItemType, ItemType.MISC),
            rarity=_parse_enum(data.get("rarity"), ItemRarity, ItemRarity.COMMON),
            weight=data.get("weight", 1.0),
            value=data.get("value", 0),
            level_requirement=data.get("level_requirement", 0),
            damage_dice=weapon.get("damage_dice"),
            damage_type=_parse_optional_enum(weapon.get("damage_type"), DamageType),
            weapon_type=_parse_optional_enum(weapon.get("weapon_type"), WeaponType),
            two_handed=weapon.get("two_handed", False),
            hit_bonus=weapon.get("hit_bonus", 0),
            damage_bonus=weapon.get("damage_bonus", 0),
            armor_bonus=armor.get("armor_bonus", 0),
            armor_type=_parse_optional_enum(armor.get("armor_type"), ArmorType),
            equipment_slot=_parse_optional_enum(data.get("slot", armor.get("slot")), EquipmentSlot),
            effect_type=_parse_optional_enum(consumable.get("effect_type"), ConsumableEffectType),
            effect_value=consumable.get("effect_value", 0),
            uses=consumable.get("uses", 1),
            flags=data.get("flags", []),
        )

    def _load_portals(self, portals_path: Path) -> int:
        """Load portal definition files."""
        count = 0
        for yaml_file in portals_path.glob("*.yaml"):
            data = self._load_yaml_file(yaml_file)
            if data and "portals" in data:
                zone_id = data.get("zone_id", "")

                for portal_data in data["portals"]:
                    try:
                        template = self._parse_portal(portal_data, zone_id)
                        self.registry.register_portal(template)
                        count += 1
                    except Exception as e:
                        self._errors.append(f"Error parsing portal in {yaml_file}: {e}")
                        logger.error(f"Error parsing portal: {e}")

        return count

    def _parse_portal(self, data: Dict, zone_id: str) -> PortalTemplate:
        """Parse portal data into template."""
        instance = data.get("instance", {})
        requirements = data.get("requirements", {})

        return PortalTemplate(
            template_id=data.get("id", data.get("template_id", "")),
            zone_id=zone_id,
            name=data.get("name", "a portal"),
            keywords=data.get("keywords", []),
            description=data.get("description", ""),
            theme_id=data.get("theme_id", data.get("theme", "")),
            theme_description=data.get("theme_description", ""),
            instance_type=instance.get("type", "dungeon"),
            difficulty_min=instance.get("difficulty_min", 1),
            difficulty_max=instance.get("difficulty_max", 10),
            max_rooms=instance.get("max_rooms", 15),
            max_players=instance.get("max_players", 8),
            min_level=requirements.get("min_level", 1),
            required_items=requirements.get("items", []),
            cooldown_s=data.get("cooldown_s", 3600),
        )

    def _load_regions(self, regions_path: Path) -> int:
        """Load region definition files."""
        count = 0
        for yaml_file in regions_path.glob("*.yaml"):
            data = self._load_yaml_file(yaml_file)
            if data:
                try:
                    template = self._parse_region(data)
                    self.registry.register_region(template)
                    count += 1
                except Exception as e:
                    self._errors.append(f"Error parsing region in {yaml_file}: {e}")
                    logger.error(f"Error parsing region: {e}")
        return count

    def _parse_region(self, data: Dict) -> RegionTemplate:
        """Parse region data into template."""
        # Parse theme with embedded LLM prompts
        theme_data = data.get("theme", {})
        theme = None
        if theme_data:
            sector_types = []
            for st in theme_data.get("sector_types", []):
                parsed = _parse_optional_enum(st, SectorType)
                if parsed:
                    sector_types.append(parsed)

            theme = RegionThemeTemplate(
                theme_id=theme_data.get("theme_id", data.get("region_id", "")),
                description=theme_data.get("description", ""),
                room_prompt=theme_data.get("room_prompt", ""),
                mob_prompt=theme_data.get("mob_prompt", ""),
                item_prompt=theme_data.get("item_prompt", ""),
                vocabulary=theme_data.get("vocabulary", []),
                forbidden_words=theme_data.get("forbidden_words", []),
                sector_types=sector_types,
                mob_templates=theme_data.get("mob_templates", []),
                item_templates=theme_data.get("item_templates", []),
                ambient_messages=theme_data.get("ambient_messages", []),
            )

        # Parse endpoints
        endpoints = []
        for room_id, ep_data in data.get("endpoints", {}).items():
            direction = Direction.from_string(ep_data.get("direction", ""))
            if direction:
                coord_data = ep_data.get("coordinate", {})
                coordinate = WorldCoordinate.from_dict(coord_data)
                endpoints.append(RegionEndpointTemplate(
                    static_room_id=room_id,
                    direction=direction,
                    coordinate=coordinate,
                ))

        # Parse waypoints
        waypoints = []
        for wp_data in data.get("waypoints", []):
            coord_data = wp_data if isinstance(wp_data, dict) and "x" in wp_data else wp_data.get("coordinate", wp_data)
            if isinstance(coord_data, dict):
                coordinate = WorldCoordinate.from_dict(coord_data)
                waypoints.append(RegionWaypointTemplate(
                    coordinate=coordinate,
                    name=wp_data.get("name", "") if isinstance(wp_data, dict) else "",
                    is_required=wp_data.get("is_required", True) if isinstance(wp_data, dict) else True,
                ))

        # Parse generation config
        generation = data.get("generation", {})

        return RegionTemplate(
            template_id=data.get("region_id", data.get("template_id", "")),
            name=data.get("name", "Unnamed Region"),
            theme=theme,
            endpoints=endpoints,
            waypoints=waypoints,
            min_rooms=generation.get("min_rooms", data.get("min_rooms", 5)),
            max_rooms=generation.get("max_rooms", data.get("max_rooms", 15)),
            difficulty_min=generation.get("difficulty_min", data.get("difficulty_min", 1)),
            difficulty_max=generation.get("difficulty_max", data.get("difficulty_max", 5)),
            mob_density=generation.get("mob_density", data.get("mob_density", 0.3)),
            item_density=generation.get("item_density", data.get("item_density", 0.1)),
            branch_chance=generation.get("branch_chance", data.get("branch_chance", 0.2)),
            primary_sector_type=_parse_enum(
                data.get("primary_sector_type"),
                SectorType,
                SectorType.FOREST
            ),
        )


def load_world(world_path: str) -> Dict[str, Any]:
    """
    Convenience function to load world content (synchronous, local registry).

    Returns load statistics.
    """
    loader = WorldLoader(world_path)
    return loader.load_all()


async def load_world_distributed(world_path: str) -> Dict[str, Any]:
    """
    Load world content into the distributed template registry.

    This is the preferred method for multi-process deployments.
    Returns load statistics.
    """
    loader = DistributedWorldLoader(world_path)
    return await loader.load_all()


async def load_zone_distributed(world_path: str, zone_id: str) -> Dict[str, Any]:
    """
    Load a specific zone's content into the distributed template registry.

    This is used by zone workers to load only their zone's content.
    Other zone workers load their respective content, and all content
    is aggregated in the shared distributed registry.

    Args:
        world_path: Path to world data directory
        zone_id: Zone identifier (e.g., "ravenmoor", "ironvein")

    Returns load statistics for the specific zone.
    """
    loader = DistributedWorldLoader(world_path)
    return await loader.load_zone(zone_id)


class DistributedWorldLoader:
    """
    Loads world data from YAML files into the distributed registry.

    Uses batch registration for efficient loading via Ray.
    """

    def __init__(self, world_path: str):
        self.world_path = Path(world_path)
        self._zones_loaded: List[str] = []
        self._errors: List[str] = []

    async def load_all(self) -> Dict[str, Any]:
        """
        Load all world content into the distributed registry.

        Returns dict with load statistics.
        """
        stats = {
            "rooms": 0,
            "mobs": 0,
            "items": 0,
            "portals": 0,
            "regions": 0,
            "zones": 0,
            "errors": [],
        }

        logger.info(f"Loading world (distributed) from: {self.world_path}")

        # Get the distributed registry actor
        try:
            registry = get_template_registry_actor()
        except ValueError as e:
            logger.error(f"Cannot load world: {e}")
            stats["errors"].append(str(e))
            return stats

        # Load zones first (metadata only, no registration needed)
        zones_path = self.world_path / "zones"
        if zones_path.exists():
            stats["zones"] = self._load_zones(zones_path)

        # Load and register rooms
        rooms_path = self.world_path / "rooms"
        if rooms_path.exists():
            rooms = self._collect_rooms(rooms_path)
            if rooms:
                count = await registry.register_rooms_batch.remote(rooms)
                stats["rooms"] = count

        # Load and register mobs
        mobs_path = self.world_path / "mobs"
        if mobs_path.exists():
            mobs = self._collect_mobs(mobs_path)
            if mobs:
                count = await registry.register_mobs_batch.remote(mobs)
                stats["mobs"] = count

        # Load and register items
        items_path = self.world_path / "items"
        if items_path.exists():
            items = self._collect_items(items_path)
            if items:
                count = await registry.register_items_batch.remote(items)
                stats["items"] = count

        # Load and register portals
        portals_path = self.world_path / "portals"
        if portals_path.exists():
            portals = self._collect_portals(portals_path)
            if portals:
                count = await registry.register_portals_batch.remote(portals)
                stats["portals"] = count

        # Load and register regions
        regions_path = self.world_path / "regions"
        if regions_path.exists():
            regions = self._collect_regions(regions_path)
            if regions:
                count = await registry.register_regions_batch.remote(regions)
                stats["regions"] = count

        stats["errors"] = self._errors.copy()

        logger.info(
            f"World loaded (distributed): {stats['rooms']} rooms, "
            f"{stats['mobs']} mobs, {stats['items']} items, "
            f"{stats['portals']} portals, {stats['regions']} regions, "
            f"{len(stats['errors'])} errors"
        )

        return stats

    async def load_zone(self, zone_id: str) -> Dict[str, Any]:
        """
        Load a specific zone's content into the distributed registry.

        Only loads rooms, mobs, and items for the specified zone.
        This allows zone workers to load only their content.

        Args:
            zone_id: Zone identifier (e.g., "ravenmoor", "ironvein")

        Returns dict with load statistics for the zone.
        """
        stats = {
            "zone_id": zone_id,
            "rooms": 0,
            "mobs": 0,
            "items": 0,
            "errors": [],
        }

        logger.info(f"Loading zone (distributed): {zone_id} from {self.world_path}")

        # Get the distributed registry actor
        try:
            registry = get_template_registry_actor()
        except ValueError as e:
            logger.error(f"Cannot load zone {zone_id}: {e}")
            stats["errors"].append(str(e))
            return stats

        # Load zone-specific rooms
        rooms_file = self.world_path / "rooms" / f"{zone_id}.yaml"
        if rooms_file.exists():
            rooms = self._collect_rooms_from_file(rooms_file)
            if rooms:
                count = await registry.register_rooms_batch.remote(rooms)
                stats["rooms"] = count
        else:
            logger.warning(f"No rooms file for zone {zone_id}: {rooms_file}")

        # Load zone-specific mobs
        mobs_file = self.world_path / "mobs" / f"{zone_id}.yaml"
        if mobs_file.exists():
            mobs = self._collect_mobs_from_file(mobs_file)
            if mobs:
                count = await registry.register_mobs_batch.remote(mobs)
                stats["mobs"] = count
        else:
            logger.warning(f"No mobs file for zone {zone_id}: {mobs_file}")

        # Load zone-specific items
        items_file = self.world_path / "items" / f"{zone_id}.yaml"
        if items_file.exists():
            items = self._collect_items_from_file(items_file)
            if items:
                count = await registry.register_items_batch.remote(items)
                stats["items"] = count
        else:
            logger.warning(f"No items file for zone {zone_id}: {items_file}")

        stats["errors"] = self._errors.copy()

        logger.info(
            f"Zone {zone_id} loaded (distributed): {stats['rooms']} rooms, "
            f"{stats['mobs']} mobs, {stats['items']} items, "
            f"{len(stats['errors'])} errors"
        )

        return stats

    def _collect_rooms_from_file(self, yaml_file: Path) -> List[RoomTemplate]:
        """Collect room templates from a specific file."""
        rooms = []
        data = self._load_yaml_file(yaml_file)
        if data and "rooms" in data:
            zone_id = data.get("zone_id", yaml_file.stem)
            for room_data in data["rooms"]:
                try:
                    template = self._parse_room(room_data, zone_id)
                    rooms.append(template)
                except Exception as e:
                    self._errors.append(f"Error parsing room in {yaml_file}: {e}")
                    logger.error(f"Error parsing room: {e}")
        return rooms

    def _collect_mobs_from_file(self, yaml_file: Path) -> List[MobTemplate]:
        """Collect mob templates from a specific file."""
        mobs = []
        data = self._load_yaml_file(yaml_file)
        if data and "mobs" in data:
            zone_id = data.get("zone_id", "")
            for mob_data in data["mobs"]:
                try:
                    template = self._parse_mob(mob_data, zone_id)
                    mobs.append(template)
                except Exception as e:
                    self._errors.append(f"Error parsing mob in {yaml_file}: {e}")
                    logger.error(f"Error parsing mob: {e}")
        return mobs

    def _collect_items_from_file(self, yaml_file: Path) -> List[ItemTemplate]:
        """Collect item templates from a specific file."""
        items = []
        data = self._load_yaml_file(yaml_file)
        if data and "items" in data:
            zone_id = data.get("zone_id", "")
            for item_data in data["items"]:
                try:
                    template = self._parse_item(item_data, zone_id)
                    items.append(template)
                except Exception as e:
                    self._errors.append(f"Error parsing item in {yaml_file}: {e}")
                    logger.error(f"Error parsing item: {e}")
        return items

    def _load_yaml_file(self, path: Path) -> Optional[Dict]:
        """Load and parse a YAML file."""
        try:
            with open(path, "r") as f:
                return yaml.safe_load(f)
        except Exception as e:
            self._errors.append(f"Error loading {path}: {e}")
            logger.error(f"Error loading {path}: {e}")
            return None

    def _load_zones(self, zones_path: Path) -> int:
        """Load zone metadata files."""
        count = 0
        for yaml_file in zones_path.glob("*.yaml"):
            data = self._load_yaml_file(yaml_file)
            if data:
                zone_id = yaml_file.stem
                self._zones_loaded.append(zone_id)
                count += 1
                logger.debug(f"Loaded zone: {zone_id}")
        return count

    def _collect_rooms(self, rooms_path: Path) -> List[RoomTemplate]:
        """Collect all room templates from files."""
        rooms = []
        for yaml_file in rooms_path.glob("*.yaml"):
            data = self._load_yaml_file(yaml_file)
            if data and "rooms" in data:
                zone_id = data.get("zone_id", yaml_file.stem)
                for room_data in data["rooms"]:
                    try:
                        template = self._parse_room(room_data, zone_id)
                        rooms.append(template)
                    except Exception as e:
                        self._errors.append(f"Error parsing room in {yaml_file}: {e}")
                        logger.error(f"Error parsing room: {e}")
        return rooms

    def _parse_room(self, data: Dict, zone_id: str) -> RoomTemplate:
        """Parse room data into template."""
        return RoomTemplate(
            template_id=data.get("id", data.get("template_id", "")),
            zone_id=zone_id,
            vnum=data.get("vnum", 0),
            name=data.get("name", "A Room"),
            short_description=data.get("short_description", data.get("name", "A room")),
            long_description=data.get("long_description", "You see nothing special."),
            exits=data.get("exits", {}),
            sector_type=_parse_enum(data.get("sector_type"), SectorType, SectorType.INSIDE),
            flags=data.get("flags", []),
            ambient_messages=data.get("ambient_messages", []),
            mob_spawns=data.get("mob_spawns", data.get("mobs", [])),
            item_spawns=data.get("item_spawns", data.get("items", [])),
            respawn_interval_s=data.get("respawn_interval_s", 300),
        )

    def _collect_mobs(self, mobs_path: Path) -> List[MobTemplate]:
        """Collect all mob templates from files."""
        mobs = []
        for yaml_file in mobs_path.glob("*.yaml"):
            data = self._load_yaml_file(yaml_file)
            if data and "mobs" in data:
                zone_id = data.get("zone_id", "")
                for mob_data in data["mobs"]:
                    try:
                        template = self._parse_mob(mob_data, zone_id)
                        mobs.append(template)
                    except Exception as e:
                        self._errors.append(f"Error parsing mob in {yaml_file}: {e}")
                        logger.error(f"Error parsing mob: {e}")
        return mobs

    def _parse_mob(self, data: Dict, zone_id: str) -> MobTemplate:
        """Parse mob data into template."""
        stats = data.get("stats", {})
        behavior = data.get("behavior", {})
        loot = data.get("loot", {})

        return MobTemplate(
            template_id=data.get("id", data.get("template_id", "")),
            zone_id=zone_id,
            vnum=data.get("vnum", 0),
            name=data.get("name", "a creature"),
            keywords=data.get("keywords", []),
            short_description=data.get("short_description", ""),
            long_description=data.get("long_description", ""),
            level=data.get("level", stats.get("level", 1)),
            health=stats.get("health", stats.get("max_health", 100)),
            mana=stats.get("mana", stats.get("max_mana", 50)),
            strength=stats.get("strength", 10),
            dexterity=stats.get("dexterity", 10),
            constitution=stats.get("constitution", 10),
            intelligence=stats.get("intelligence", 10),
            wisdom=stats.get("wisdom", 10),
            charisma=stats.get("charisma", 10),
            damage_dice=data.get("damage_dice", stats.get("damage_dice", "1d6")),
            damage_type=_parse_enum(data.get("damage_type"), DamageType, DamageType.BLUDGEONING),
            armor_class=stats.get("armor_class", 10),
            attack_bonus=stats.get("attack_bonus", 0),
            behavior_type=_parse_enum(behavior.get("type"), BehaviorType, BehaviorType.PASSIVE),
            combat_style=_parse_enum(behavior.get("combat_style"), CombatStyle, CombatStyle.TACTICIAN),
            aggro_radius=behavior.get("aggro_radius", 0),
            flee_threshold=behavior.get("flee_threshold", 0.2),
            gold_min=loot.get("gold_min", 0),
            gold_max=loot.get("gold_max", 10),
            loot_table=loot.get("items", []),
            experience_value=data.get("experience", 100),
            flags=data.get("flags", []),
            dialogue=data.get("dialogue"),
        )

    def _collect_items(self, items_path: Path) -> List[ItemTemplate]:
        """Collect all item templates from files."""
        items = []
        for yaml_file in items_path.glob("*.yaml"):
            data = self._load_yaml_file(yaml_file)
            if data and "items" in data:
                zone_id = data.get("zone_id", "")
                for item_data in data["items"]:
                    try:
                        template = self._parse_item(item_data, zone_id)
                        items.append(template)
                    except Exception as e:
                        self._errors.append(f"Error parsing item in {yaml_file}: {e}")
                        logger.error(f"Error parsing item: {e}")
        return items

    def _parse_item(self, data: Dict, zone_id: str) -> ItemTemplate:
        """Parse item data into template."""
        weapon = data.get("weapon", {})
        armor = data.get("armor", {})
        consumable = data.get("consumable", {})

        return ItemTemplate(
            template_id=data.get("id", data.get("template_id", "")),
            zone_id=zone_id,
            vnum=data.get("vnum", 0),
            name=data.get("name", "an item"),
            keywords=data.get("keywords", []),
            short_description=data.get("short_description", ""),
            long_description=data.get("long_description", ""),
            item_type=_parse_enum(data.get("type", data.get("item_type")), ItemType, ItemType.MISC),
            rarity=_parse_enum(data.get("rarity"), ItemRarity, ItemRarity.COMMON),
            weight=data.get("weight", 1.0),
            value=data.get("value", 0),
            level_requirement=data.get("level_requirement", 0),
            damage_dice=weapon.get("damage_dice"),
            damage_type=_parse_optional_enum(weapon.get("damage_type"), DamageType),
            weapon_type=_parse_optional_enum(weapon.get("weapon_type"), WeaponType),
            two_handed=weapon.get("two_handed", False),
            hit_bonus=weapon.get("hit_bonus", 0),
            damage_bonus=weapon.get("damage_bonus", 0),
            armor_bonus=armor.get("armor_bonus", 0),
            armor_type=_parse_optional_enum(armor.get("armor_type"), ArmorType),
            equipment_slot=_parse_optional_enum(data.get("slot", armor.get("slot")), EquipmentSlot),
            effect_type=_parse_optional_enum(consumable.get("effect_type"), ConsumableEffectType),
            effect_value=consumable.get("effect_value", 0),
            uses=consumable.get("uses", 1),
            flags=data.get("flags", []),
        )

    def _collect_portals(self, portals_path: Path) -> List[PortalTemplate]:
        """Collect all portal templates from files."""
        portals = []
        for yaml_file in portals_path.glob("*.yaml"):
            data = self._load_yaml_file(yaml_file)
            if data and "portals" in data:
                zone_id = data.get("zone_id", "")
                for portal_data in data["portals"]:
                    try:
                        template = self._parse_portal(portal_data, zone_id)
                        portals.append(template)
                    except Exception as e:
                        self._errors.append(f"Error parsing portal in {yaml_file}: {e}")
                        logger.error(f"Error parsing portal: {e}")
        return portals

    def _parse_portal(self, data: Dict, zone_id: str) -> PortalTemplate:
        """Parse portal data into template."""
        instance = data.get("instance", {})
        requirements = data.get("requirements", {})

        return PortalTemplate(
            template_id=data.get("id", data.get("template_id", "")),
            zone_id=zone_id,
            name=data.get("name", "a portal"),
            keywords=data.get("keywords", []),
            description=data.get("description", ""),
            theme_id=data.get("theme_id", data.get("theme", "")),
            theme_description=data.get("theme_description", ""),
            instance_type=instance.get("type", "dungeon"),
            difficulty_min=instance.get("difficulty_min", 1),
            difficulty_max=instance.get("difficulty_max", 10),
            max_rooms=instance.get("max_rooms", 15),
            max_players=instance.get("max_players", 8),
            min_level=requirements.get("min_level", 1),
            required_items=requirements.get("items", []),
            cooldown_s=data.get("cooldown_s", 3600),
        )

    def _collect_regions(self, regions_path: Path) -> List[RegionTemplate]:
        """Collect all region templates from files."""
        regions = []
        for yaml_file in regions_path.glob("*.yaml"):
            data = self._load_yaml_file(yaml_file)
            if data:
                try:
                    template = self._parse_region(data)
                    regions.append(template)
                except Exception as e:
                    self._errors.append(f"Error parsing region in {yaml_file}: {e}")
                    logger.error(f"Error parsing region: {e}")
        return regions

    def _parse_region(self, data: Dict) -> RegionTemplate:
        """Parse region data into template."""
        # Parse theme
        theme_data = data.get("theme", {})
        theme = None
        if theme_data:
            sector_types = []
            for st in theme_data.get("sector_types", []):
                try:
                    sector_types.append(SectorType(st))
                except ValueError:
                    logger.warning(f"Unknown sector type: {st}")

            theme = RegionThemeTemplate(
                theme_id=theme_data.get("theme_id", ""),
                description=theme_data.get("description", ""),
                room_prompt=theme_data.get("room_prompt", ""),
                mob_prompt=theme_data.get("mob_prompt", ""),
                item_prompt=theme_data.get("item_prompt", ""),
                vocabulary=theme_data.get("vocabulary", []),
                forbidden_words=theme_data.get("forbidden_words", []),
                sector_types=sector_types,
                mob_templates=theme_data.get("mob_templates", []),
                item_templates=theme_data.get("item_templates", []),
                ambient_messages=theme_data.get("ambient_messages", []),
            )

        # Parse endpoints
        endpoints = []
        for room_id, ep_data in data.get("endpoints", {}).items():
            direction_str = ep_data.get("direction", "north")
            try:
                direction = Direction(direction_str)
            except ValueError:
                direction = Direction.NORTH
                logger.warning(f"Unknown direction {direction_str}, defaulting to north")

            coord_data = ep_data.get("coordinate", {})
            coordinate = WorldCoordinate(
                x=coord_data.get("x", 0),
                y=coord_data.get("y", 0),
                z=coord_data.get("z", 0),
            )

            endpoints.append(RegionEndpointTemplate(
                static_room_id=room_id,
                direction=direction,
                coordinate=coordinate,
            ))

        # Parse waypoints
        waypoints = []
        for wp_data in data.get("waypoints", []):
            coord_data = wp_data if isinstance(wp_data, dict) and "x" in wp_data else wp_data
            coordinate = WorldCoordinate(
                x=coord_data.get("x", 0),
                y=coord_data.get("y", 0),
                z=coord_data.get("z", 0),
            )
            waypoints.append(RegionWaypointTemplate(
                coordinate=coordinate,
                name=coord_data.get("name", ""),
                is_required=coord_data.get("is_required", True),
            ))

        # Parse generation config
        gen_data = data.get("generation", {})

        # Parse primary sector type
        primary_sector_str = data.get("primary_sector_type", "forest")
        try:
            primary_sector_type = SectorType(primary_sector_str)
        except ValueError:
            primary_sector_type = SectorType.FOREST

        return RegionTemplate(
            template_id=data.get("region_id", data.get("template_id", "")),
            name=data.get("name", "Unnamed Region"),
            theme=theme,
            endpoints=endpoints,
            waypoints=waypoints,
            min_rooms=gen_data.get("min_rooms", 5),
            max_rooms=gen_data.get("max_rooms", 15),
            difficulty_min=gen_data.get("difficulty_min", 1),
            difficulty_max=gen_data.get("difficulty_max", 5),
            mob_density=gen_data.get("mob_density", 0.3),
            item_density=gen_data.get("item_density", 0.1),
            branch_chance=gen_data.get("branch_chance", 0.2),
            primary_sector_type=primary_sector_type,
        )
