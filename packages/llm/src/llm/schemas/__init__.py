"""
LLM Output Schemas

Pydantic models for structured LLM outputs using PydanticAI.
These schemas ensure type-safe, validated generation results.
"""

from .room import (
    RoomExitDirection,
    GeneratedRoomExit,
    GeneratedRoom,
    RoomGenerationContext,
    AdjacentRoomSummary,
)

from .mob import (
    MobDisposition,
    MobAbility,
    GeneratedMob,
    MobGenerationContext,
)

from .item import (
    WeaponStats,
    ArmorStats,
    ConsumableEffect,
    MagicalProperty,
    GeneratedItem,
    ItemGenerationContext,
)

from .combat import (
    CombatNarration,
    CombatNarrationContext,
)

from .dialogue import (
    DialogueResponse,
    DialogueContext,
    NPCMood,
)

from .quest import (
    QuestArchetype,
    ZoneType,
    ZONE_QUEST_PREFERENCES,
    GeneratedReward,
    InstancedSpawn,
    GeneratedObjective,
    GeneratedQuest,
    ZoneQuestTheme,
    QuestGenerationContext,
)

from .crafted_item import (
    DAMAGE_DICE_BY_LEVEL,
    ARMOR_BY_LEVEL,
    BONUS_BY_RARITY,
    MAX_PROPERTIES_BY_RARITY,
    QUALITY_MODIFIERS,
    ComponentQuality,
    MagicalPropertyType,
    CraftedMagicalProperty,
    CraftedWeaponStats,
    CraftedArmorStats,
    ComponentDescription,
    GeneratedCraftedItem,
    CraftingContext,
    CraftingResultType,
    CraftingResult,
)

__all__ = [
    # Room schemas
    "RoomExitDirection",
    "GeneratedRoomExit",
    "GeneratedRoom",
    "RoomGenerationContext",
    "AdjacentRoomSummary",
    # Mob schemas
    "MobDisposition",
    "MobAbility",
    "GeneratedMob",
    "MobGenerationContext",
    # Item schemas
    "WeaponStats",
    "ArmorStats",
    "ConsumableEffect",
    "MagicalProperty",
    "GeneratedItem",
    "ItemGenerationContext",
    # Combat schemas
    "CombatNarration",
    "CombatNarrationContext",
    # Dialogue schemas
    "DialogueResponse",
    "DialogueContext",
    "NPCMood",
    # Quest schemas
    "QuestArchetype",
    "ZoneType",
    "ZONE_QUEST_PREFERENCES",
    "GeneratedReward",
    "InstancedSpawn",
    "GeneratedObjective",
    "GeneratedQuest",
    "ZoneQuestTheme",
    "QuestGenerationContext",
    # Crafted item schemas
    "DAMAGE_DICE_BY_LEVEL",
    "ARMOR_BY_LEVEL",
    "BONUS_BY_RARITY",
    "MAX_PROPERTIES_BY_RARITY",
    "QUALITY_MODIFIERS",
    "ComponentQuality",
    "MagicalPropertyType",
    "CraftedMagicalProperty",
    "CraftedWeaponStats",
    "CraftedArmorStats",
    "ComponentDescription",
    "GeneratedCraftedItem",
    "CraftingContext",
    "CraftingResultType",
    "CraftingResult",
]
