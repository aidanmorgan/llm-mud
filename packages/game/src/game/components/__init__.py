"""
Game Component Data Classes

All component types used in the MUD game. Each component is a dataclass
that inherits from ComponentData and stores specific data for entities.

Components are organized by category:
- Identity: Names, descriptions, keywords
- Spatial: Location, room data, exits
- Stats: Health, mana, attributes
- Combat: Targeting, damage, abilities
- Inventory: Items, equipment, containers
- AI: Mob behavior, personality
- Player: Session, progress, quests
- Portal: Dynamic instance connections
"""

from .identity import (
    IdentityData,
    StaticIdentityData,
    DynamicIdentityData,
)

from .spatial import (
    LocationData,
    RoomData,
    StaticRoomData,
    DynamicRoomData,
    ExitData,
    Direction,
    SectorType,
    PersistenceLevel,
    WorldCoordinate,
)

from .region import (
    RegionTheme,
    RegionEndpoint,
    RegionWaypoint,
    RegionGenerationConfig,
    DynamicRegionData,
    RegionRoomData,
    RegionState,
)

from .stats import (
    StatsData,
    PlayerStatsData,
    MobStatsData,
    AttributeBlock,
)

from .combat import (
    CombatData,
    DamageType,
    CombatState,
)

from .inventory import (
    ContainerData,
    EquipmentSlotsData,
    ItemData,
    WeaponData,
    ArmorData,
    ConsumableData,
    EquipmentSlot,
    ItemType,
    ItemRarity,
    WeaponType,
    ArmorType,
    ConsumableEffectType,
)

from .ai import (
    AIData,
    StaticAIData,
    DynamicAIData,
    DialogueData,
    BehaviorType,
    CombatStyle,
    PersonalityTrait,
)

from .player import (
    PlayerConnectionData,
    PlayerProgressData,
    QuestLogData,
)

from .portal import (
    PortalData,
    InstanceData,
    InstanceType,
)

from .position import (
    PositionData,
    Position,
)

from .skills import (
    SkillCategory,
    TargetType,
    EffectType,
    DamageSchool,
    SkillState,
    SkillResult,
    EffectTick,
    CooldownInfo,
    SkillDefinition,
    ActiveEffect,
    SkillSetData,
    ActiveEffectsData,
)

from .economy import (
    ShopItem,
    ShopData,
    TradeOffer,
    TradeData,
    TradeState,
    BankAccountData,
)

from .character import (
    CharacterClass,
    CharacterRace,
    CreationState,
    StatModifiers,
    ClassDefinition,
    RaceDefinition,
    ClassData,
    RaceData,
    CharacterCreationData,
    ClassTemplate,
    RaceTemplate,
)

from .journey import (
    WeatherType,
    MountType,
    SupplyType,
    SupplyItem,
    MountData,
    SupplyData,
    WeatherData,
    WaypointVisit,
    JourneyData,
    RegionWeatherData,
)

from .group import (
    GroupRole,
    LootRule,
    ExpShareMode,
    GroupMember,
    GroupInvite,
    GroupData,
    GroupMembershipData,
    SocialData,
    SOCIAL_EMOTES,
    get_social_emote,
)

from .world import (
    TimeOfDay,
    Season,
    MoonPhase,
    WorldEventType,
    WorldEvent,
    GameTime,
    WorldStateData,
    ZoneStateData,
    RoomVisibilityData,
)

from .preferences import (
    ColorTheme,
    PromptToken,
    AliasData,
    PreferencesData,
    format_prompt,
    DEFAULT_PROMPT,
    DEFAULT_BATTLE_PROMPT,
)

from .quests import (
    QuestState,
    ObjectiveType,
    QuestRarity,
    QuestObjective,
    QuestReward,
    QuestDefinition,
    ActiveQuest,
    QuestLogData,
    register_quest,
    get_quest_definition,
    get_all_quest_definitions,
    get_quests_by_giver,
    get_quests_in_chain,
    check_quest_requirements,
)

from .quest_instance import (
    QuestInstanceData,
    QuestSpawnedEntityData,
    GeneratedQuestData,
    is_visible_to_player,
)

from .crafting import (
    ComponentQuality,
    ComponentCategory,
    GatheringSkill,
    CraftingProfession,
    QUALITY_MODIFIERS,
    CraftingComponentData,
    GatherNodeData,
    CraftingRecipeData,
    RecipeBookData,
    CraftingSkillData,
    WorkbenchData,
    components_match,
    get_combo_key,
)

from .leveling import (
    LevelReward,
    LevelRequirement,
    GuildConfig,
    GuildClassDefinition,
    LevelingData,
    LevelUpQueueData,
    GuildRoomData,
    calculate_xp_for_level,
    calculate_total_xp_to_level,
    get_default_title,
    DEFAULT_TITLES,
)

from .proficiency import (
    ProficiencySkill,
    ProficiencyEntry,
    ProficiencyData,
    SkillBenefits,
    GATHERING_SKILLS,
    CRAFTING_SKILLS,
    UTILITY_SKILLS,
    calculate_skill_benefits,
    calculate_xp_for_skill_level,
    calculate_activity_xp,
    GATHERING_XP_BASE,
    CRAFTING_XP_BASE,
    DISMANTLING_XP_BASE,
    FISHING_XP_BASE,
    COOKING_XP_BASE,
    DEFAULT_RACE_PROFICIENCY_BONUSES,
    DEFAULT_CLASS_PROFICIENCY_BONUSES,
)

__all__ = [
    # Identity
    "IdentityData",
    "StaticIdentityData",
    "DynamicIdentityData",
    # Spatial
    "LocationData",
    "RoomData",
    "StaticRoomData",
    "DynamicRoomData",
    "ExitData",
    "Direction",
    "SectorType",
    "PersistenceLevel",
    "WorldCoordinate",
    # Region
    "RegionTheme",
    "RegionEndpoint",
    "RegionWaypoint",
    "RegionGenerationConfig",
    "DynamicRegionData",
    "RegionRoomData",
    "RegionState",
    # Stats
    "StatsData",
    "PlayerStatsData",
    "MobStatsData",
    "AttributeBlock",
    # Combat
    "CombatData",
    "DamageType",
    "CombatState",
    # Inventory
    "ContainerData",
    "EquipmentSlotsData",
    "ItemData",
    "WeaponData",
    "ArmorData",
    "ConsumableData",
    "EquipmentSlot",
    "ItemType",
    "ItemRarity",
    "WeaponType",
    "ArmorType",
    "ConsumableEffectType",
    # AI
    "AIData",
    "StaticAIData",
    "DynamicAIData",
    "DialogueData",
    "BehaviorType",
    "CombatStyle",
    "PersonalityTrait",
    # Player
    "PlayerConnectionData",
    "PlayerProgressData",
    "QuestLogData",
    # Portal
    "PortalData",
    "InstanceData",
    "InstanceType",
    # Position
    "PositionData",
    "Position",
    # Skills
    "SkillCategory",
    "TargetType",
    "EffectType",
    "DamageSchool",
    "SkillState",
    "SkillResult",
    "EffectTick",
    "CooldownInfo",
    "SkillDefinition",
    "ActiveEffect",
    "SkillSetData",
    "ActiveEffectsData",
    # Economy
    "ShopItem",
    "ShopData",
    "TradeOffer",
    "TradeData",
    "TradeState",
    "BankAccountData",
    # Character
    "CharacterClass",
    "CharacterRace",
    "CreationState",
    "StatModifiers",
    "ClassDefinition",
    "RaceDefinition",
    "ClassData",
    "RaceData",
    "CharacterCreationData",
    "ClassTemplate",
    "RaceTemplate",
    # Journey
    "WeatherType",
    "MountType",
    "SupplyType",
    "SupplyItem",
    "MountData",
    "SupplyData",
    "WeatherData",
    "WaypointVisit",
    "JourneyData",
    "RegionWeatherData",
    # Group & Social
    "GroupRole",
    "LootRule",
    "ExpShareMode",
    "GroupMember",
    "GroupInvite",
    "GroupData",
    "GroupMembershipData",
    "SocialData",
    "SOCIAL_EMOTES",
    "get_social_emote",
    # World
    "TimeOfDay",
    "Season",
    "MoonPhase",
    "WorldEventType",
    "WorldEvent",
    "GameTime",
    "WorldStateData",
    "ZoneStateData",
    "RoomVisibilityData",
    # Preferences
    "ColorTheme",
    "PromptToken",
    "AliasData",
    "PreferencesData",
    "format_prompt",
    "DEFAULT_PROMPT",
    "DEFAULT_BATTLE_PROMPT",
    # Quests
    "QuestState",
    "ObjectiveType",
    "QuestRarity",
    "QuestObjective",
    "QuestReward",
    "QuestDefinition",
    "ActiveQuest",
    "QuestLogData",
    "register_quest",
    "get_quest_definition",
    "get_all_quest_definitions",
    "get_quests_by_giver",
    "get_quests_in_chain",
    "check_quest_requirements",
    # Quest Instance (Dynamic Quest Entities)
    "QuestInstanceData",
    "QuestSpawnedEntityData",
    "GeneratedQuestData",
    "is_visible_to_player",
    # Crafting
    "ComponentQuality",
    "ComponentCategory",
    "GatheringSkill",
    "CraftingProfession",
    "QUALITY_MODIFIERS",
    "CraftingComponentData",
    "GatherNodeData",
    "CraftingRecipeData",
    "RecipeBookData",
    "CraftingSkillData",
    "WorkbenchData",
    "components_match",
    "get_combo_key",
    # Leveling & Guilds
    "LevelReward",
    "LevelRequirement",
    "GuildConfig",
    "GuildClassDefinition",
    "LevelingData",
    "LevelUpQueueData",
    "GuildRoomData",
    "calculate_xp_for_level",
    "calculate_total_xp_to_level",
    "get_default_title",
    "DEFAULT_TITLES",
    # Proficiency Skills
    "ProficiencySkill",
    "ProficiencyEntry",
    "ProficiencyData",
    "SkillBenefits",
    "GATHERING_SKILLS",
    "CRAFTING_SKILLS",
    "UTILITY_SKILLS",
    "calculate_skill_benefits",
    "calculate_xp_for_skill_level",
    "calculate_activity_xp",
    "GATHERING_XP_BASE",
    "CRAFTING_XP_BASE",
    "DISMANTLING_XP_BASE",
    "FISHING_XP_BASE",
    "COOKING_XP_BASE",
    "DEFAULT_RACE_PROFICIENCY_BONUSES",
    "DEFAULT_CLASS_PROFICIENCY_BONUSES",
]
