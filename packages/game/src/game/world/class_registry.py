"""
Class Registry Ray Actor

Distributed registry for class definitions with guild and leveling configuration.
Loaded from YAML at startup, queryable from any process.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
import logging

import ray

from ..components.leveling import (
    GuildClassDefinition,
    GuildConfig,
    LevelRequirement,
    LevelReward,
    get_default_title,
)

logger = logging.getLogger(__name__)

ACTOR_NAME = "class_registry"
ACTOR_NAMESPACE = "llmmud"


@ray.remote
class ClassRegistry:
    """
    Ray actor for class definitions and guild configuration.

    Features:
    - Class definitions loaded from YAML
    - Guild locations and restrictions
    - Level requirements and rewards
    - Cross-process accessible
    """

    def __init__(self):
        self._classes: Dict[str, GuildClassDefinition] = {}
        self._guild_locations: Dict[str, str] = {}  # room_id -> class_id
        self._guild_masters: Dict[str, str] = {}  # npc_id -> class_id
        self._version: int = 0

    async def register_class(self, class_def: GuildClassDefinition) -> None:
        """Register a class definition."""
        self._classes[class_def.class_id] = class_def

        # Index guild location
        self._guild_locations[class_def.guild.location_id] = class_def.class_id
        for room_id in class_def.guild.additional_rooms:
            self._guild_locations[room_id] = class_def.class_id

        # Index guild master
        self._guild_masters[class_def.guild.guild_master_id] = class_def.class_id

        self._version += 1
        logger.info(f"Registered class: {class_def.class_id}")

    async def register_class_from_dict(self, data: Dict[str, Any]) -> None:
        """Register a class from a dictionary (from YAML)."""
        class_def = _parse_class_definition(data)
        await self.register_class(class_def)

    async def get_class(self, class_id: str) -> Optional[GuildClassDefinition]:
        """Get class definition by ID."""
        return self._classes.get(class_id)

    async def get_all_classes(self) -> List[GuildClassDefinition]:
        """Get all registered classes."""
        return list(self._classes.values())

    async def get_class_ids(self) -> List[str]:
        """Get all registered class IDs."""
        return list(self._classes.keys())

    async def get_level_requirements(
        self, class_id: str, target_level: int
    ) -> Optional[LevelRequirement]:
        """Get requirements for reaching a specific level."""
        class_def = self._classes.get(class_id)
        if not class_def:
            return None

        return class_def.get_level_requirement(target_level)

    async def get_xp_for_level(self, class_id: str, level: int) -> int:
        """Get XP required for a specific level."""
        class_def = self._classes.get(class_id)
        if not class_def:
            return level * level * 1000  # Default formula

        return class_def.get_xp_for_level(level)

    async def get_title_for_level(self, class_id: str, level: int) -> str:
        """Get display title for a class and level."""
        class_def = self._classes.get(class_id)
        if not class_def:
            return get_default_title(class_id, level)

        return class_def.get_title_for_level(level)

    # Guild methods

    async def get_guild_class(self, room_id: str) -> Optional[str]:
        """Check if a room is a guild and return its class."""
        return self._guild_locations.get(room_id)

    async def can_enter_guild(self, room_id: str, player_class: str) -> bool:
        """Check if a player's class allows them to enter a guild room."""
        guild_class = self._guild_locations.get(room_id)
        if guild_class is None:
            return True  # Not a guild room
        return guild_class == player_class

    async def get_guild_rejection_message(self, room_id: str) -> Optional[str]:
        """Get the rejection message for a guild room."""
        guild_class = self._guild_locations.get(room_id)
        if guild_class and guild_class in self._classes:
            return self._classes[guild_class].guild.rejection_message
        return None

    async def get_guild_entrance_message(self, room_id: str) -> Optional[str]:
        """Get the entrance message for a guild room."""
        guild_class = self._guild_locations.get(room_id)
        if guild_class and guild_class in self._classes:
            return self._classes[guild_class].guild.entrance_message
        return None

    async def get_guild_for_class(self, class_id: str) -> Optional[GuildConfig]:
        """Get guild configuration for a class."""
        class_def = self._classes.get(class_id)
        if class_def:
            return class_def.guild
        return None

    async def get_guild_master_class(self, npc_id: str) -> Optional[str]:
        """Check if an NPC is a guild master and return their class."""
        return self._guild_masters.get(npc_id)

    async def is_guild_master(self, npc_id: str, class_id: str) -> bool:
        """Check if an NPC is the guild master for a specific class."""
        return self._guild_masters.get(npc_id) == class_id

    # Utility methods

    async def get_version(self) -> int:
        """Get current registry version for cache invalidation."""
        return self._version

    async def get_stats(self) -> Dict[str, Any]:
        """Get registry statistics."""
        return {
            "classes_registered": len(self._classes),
            "guild_locations": len(self._guild_locations),
            "guild_masters": len(self._guild_masters),
            "version": self._version,
            "class_ids": list(self._classes.keys()),
        }


# =============================================================================
# YAML Parsing Helpers
# =============================================================================


def _parse_class_definition(data: Dict[str, Any]) -> GuildClassDefinition:
    """Parse a class definition from YAML data."""
    # Parse guild config
    guild_data = data.get("guild", {})
    guild = GuildConfig(
        guild_name=guild_data.get("name", "Guild Hall"),
        location_id=guild_data.get("location_id", "ravenmoor_square"),
        guild_master_id=guild_data.get("guild_master_id", "guild_master"),
        entrance_message=guild_data.get(
            "entrance_message", "You enter the guild hall."
        ),
        rejection_message=guild_data.get(
            "rejection_message", "Only members of this class may enter."
        ),
        additional_rooms=guild_data.get("additional_rooms", []),
    )

    # Parse level requirements
    levels = {}
    levels_data = data.get("levels", {})
    for level_num, level_data in levels_data.items():
        level_num = int(level_num)

        # Parse rewards
        rewards_data = level_data.get("rewards", {})
        rewards = LevelReward(
            gold=rewards_data.get("gold", 0),
            items=rewards_data.get("items", []),
            skills=rewards_data.get("skills", []),
            title=rewards_data.get("title_override"),
        )

        levels[level_num] = LevelRequirement(
            level=level_num,
            xp_required=level_data.get("xp_required", level_num * level_num * 1000),
            title=level_data.get("title", f"Level {level_num}"),
            required_items=level_data.get("required_items", []),
            required_quests=level_data.get("required_quests", []),
            required_gold=level_data.get("required_gold", 0),
            rewards=rewards,
        )

    # Parse starting configuration
    starting = data.get("starting", {})

    return GuildClassDefinition(
        class_id=data.get("class_id", "warrior"),
        name=data.get("name", "Warrior"),
        description=data.get("description", ""),
        guild=guild,
        base_stats=data.get("base_stats", {}),
        starting_location=starting.get("location_id", "ravenmoor_square"),
        starting_equipment=starting.get("equipment", []),
        starting_skills=starting.get("skills", []),
        starting_gold=starting.get("gold", 100),
        health_per_level=data.get("health_per_level", 10),
        mana_per_level=data.get("mana_per_level", 5),
        starting_health=data.get("starting_health", 100),
        starting_mana=data.get("starting_mana", 50),
        levels=levels,
        max_level=data.get("max_level", 50),
        xp_formula=data.get("xp_formula", "level * level * 1000"),
        prime_attribute=data.get("prime_attribute", "strength"),
        armor_proficiency=data.get("armor_proficiency", []),
        weapon_proficiency=data.get("weapon_proficiency", []),
        class_skills=data.get("class_skills", []),
    )


# =============================================================================
# Lifecycle Functions
# =============================================================================


def start_class_registry() -> ray.actor.ActorHandle:
    """Start the ClassRegistry actor."""
    return ClassRegistry.options(
        name=ACTOR_NAME,
        namespace=ACTOR_NAMESPACE,
        lifetime="detached",
    ).remote()


def get_class_registry() -> ray.actor.ActorHandle:
    """Get the ClassRegistry actor handle."""
    return ray.get_actor(ACTOR_NAME, namespace=ACTOR_NAMESPACE)


def class_registry_exists() -> bool:
    """Check if the ClassRegistry actor exists."""
    try:
        ray.get_actor(ACTOR_NAME, namespace=ACTOR_NAMESPACE)
        return True
    except ValueError:
        return False


def stop_class_registry() -> None:
    """Stop the ClassRegistry actor."""
    try:
        actor = ray.get_actor(ACTOR_NAME, namespace=ACTOR_NAMESPACE)
        ray.kill(actor)
    except ValueError:
        pass


# =============================================================================
# Default Class Definitions
# =============================================================================

# These are used if no YAML files are provided
DEFAULT_CLASSES = [
    {
        "class_id": "warrior",
        "name": "Warrior",
        "description": "Masters of martial combat, warriors excel in physical prowess.",
        "guild": {
            "name": "Warriors' Barracks",
            "location_id": "ravenmoor_barracks",
            "guild_master_id": "captain_ironhelm",
            "entrance_message": "You enter the training grounds of the Warriors' Barracks.",
            "rejection_message": "The guards block your path. Only warriors may enter.",
        },
        "base_stats": {
            "strength": 16,
            "dexterity": 12,
            "constitution": 14,
            "intelligence": 8,
            "wisdom": 10,
            "charisma": 10,
        },
        "starting": {
            "location_id": "ravenmoor_barracks",
            "equipment": ["iron_sword", "leather_armor", "wooden_shield"],
            "skills": ["bash", "parry"],
        },
        "health_per_level": 12,
        "mana_per_level": 3,
        "prime_attribute": "strength",
        "levels": {
            1: {"xp_required": 0, "title": "Recruit"},
            2: {"xp_required": 1000, "title": "Trainee"},
            3: {"xp_required": 3000, "title": "Footman"},
            5: {"xp_required": 10000, "title": "Veteran"},
            10: {"xp_required": 55000, "title": "Champion"},
        },
    },
    {
        "class_id": "mage",
        "name": "Mage",
        "description": "Wielders of arcane power, mages command the forces of magic.",
        "guild": {
            "name": "The Arcane Sanctum",
            "location_id": "ravenmoor_mage_tower",
            "guild_master_id": "archmage_vaelith",
            "entrance_message": "You enter the Arcane Sanctum, magic crackling in the air.",
            "rejection_message": "An invisible barrier prevents your entry. Only mages may pass.",
        },
        "base_stats": {
            "strength": 8,
            "dexterity": 10,
            "constitution": 10,
            "intelligence": 16,
            "wisdom": 14,
            "charisma": 12,
        },
        "starting": {
            "location_id": "ravenmoor_mage_tower",
            "equipment": ["apprentice_staff", "cloth_robe"],
            "skills": ["magic_missile", "arcane_shield"],
        },
        "health_per_level": 6,
        "mana_per_level": 12,
        "prime_attribute": "intelligence",
        "levels": {
            1: {"xp_required": 0, "title": "Apprentice"},
            2: {"xp_required": 1000, "title": "Initiate"},
            3: {"xp_required": 3000, "title": "Adept"},
            5: {"xp_required": 10000, "title": "Evoker"},
            10: {"xp_required": 55000, "title": "Wizard"},
        },
    },
    {
        "class_id": "cleric",
        "name": "Cleric",
        "description": "Servants of the divine, clerics channel holy power to heal and protect.",
        "guild": {
            "name": "Temple of Light",
            "location_id": "ravenmoor_temple",
            "guild_master_id": "high_priest_aldric",
            "entrance_message": "You enter the Temple of Light, feeling a sense of peace.",
            "rejection_message": "The temple guardians bar your way. Only clerics may enter.",
        },
        "base_stats": {
            "strength": 10,
            "dexterity": 8,
            "constitution": 12,
            "intelligence": 10,
            "wisdom": 16,
            "charisma": 14,
        },
        "starting": {
            "location_id": "ravenmoor_temple",
            "equipment": ["holy_mace", "chain_mail", "wooden_shield"],
            "skills": ["cure_light", "bless"],
        },
        "health_per_level": 8,
        "mana_per_level": 10,
        "prime_attribute": "wisdom",
        "levels": {
            1: {"xp_required": 0, "title": "Acolyte"},
            2: {"xp_required": 1000, "title": "Devotee"},
            3: {"xp_required": 3000, "title": "Priest"},
            5: {"xp_required": 10000, "title": "Curate"},
            10: {"xp_required": 55000, "title": "Bishop"},
        },
    },
    {
        "class_id": "rogue",
        "name": "Rogue",
        "description": "Masters of stealth and subtlety, rogues strike from the shadows.",
        "guild": {
            "name": "The Shadow Den",
            "location_id": "ravenmoor_thieves_guild",
            "guild_master_id": "shadowmaster_vexa",
            "entrance_message": "You slip into the Shadow Den, eyes watching from darkness.",
            "rejection_message": "A voice from the shadows whispers: 'This place is not for you.'",
        },
        "base_stats": {
            "strength": 10,
            "dexterity": 16,
            "constitution": 10,
            "intelligence": 12,
            "wisdom": 10,
            "charisma": 12,
        },
        "starting": {
            "location_id": "ravenmoor_thieves_guild",
            "equipment": ["twin_daggers", "leather_armor", "lockpicks"],
            "skills": ["backstab", "hide"],
        },
        "health_per_level": 8,
        "mana_per_level": 5,
        "prime_attribute": "dexterity",
        "levels": {
            1: {"xp_required": 0, "title": "Pickpocket"},
            2: {"xp_required": 1000, "title": "Cutpurse"},
            3: {"xp_required": 3000, "title": "Burglar"},
            5: {"xp_required": 10000, "title": "Thief"},
            10: {"xp_required": 55000, "title": "Assassin"},
        },
    },
    {
        "class_id": "ranger",
        "name": "Ranger",
        "description": "Wardens of the wild, rangers are skilled hunters and survivalists.",
        "guild": {
            "name": "The Verdant Lodge",
            "location_id": "ravenmoor_rangers_lodge",
            "guild_master_id": "huntmaster_theron",
            "entrance_message": "You enter the Verdant Lodge, the scent of pine and leather filling the air.",
            "rejection_message": "The ranger at the door shakes their head. 'The Lodge is for rangers only.'",
        },
        "base_stats": {
            "strength": 12,
            "dexterity": 14,
            "constitution": 12,
            "intelligence": 10,
            "wisdom": 14,
            "charisma": 8,
        },
        "starting": {
            "location_id": "ravenmoor_rangers_lodge",
            "equipment": ["longbow", "hunting_knife", "leather_armor"],
            "skills": ["track", "snare"],
        },
        "health_per_level": 10,
        "mana_per_level": 6,
        "prime_attribute": "dexterity",
        "levels": {
            1: {"xp_required": 0, "title": "Scout"},
            2: {"xp_required": 1000, "title": "Tracker"},
            3: {"xp_required": 3000, "title": "Pathfinder"},
            5: {"xp_required": 10000, "title": "Warden"},
            10: {"xp_required": 55000, "title": "Ranger"},
        },
    },
]


async def register_default_classes(registry: ray.actor.ActorHandle) -> None:
    """Register default class definitions."""
    for class_data in DEFAULT_CLASSES:
        await registry.register_class_from_dict.remote(class_data)
    logger.info(f"Registered {len(DEFAULT_CLASSES)} default classes")
