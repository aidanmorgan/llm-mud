"""
Game Package

Contains all game logic, components, systems, and commands for LLM-MUD.
"""

# Components are the data structures attached to entities
from .components import (
    # Identity
    IdentityData,
    StaticIdentityData,
    DynamicIdentityData,
    # Spatial
    LocationData,
    RoomData,
    StaticRoomData,
    DynamicRoomData,
    ExitData,
    # Stats
    StatsData,
    PlayerStatsData,
    MobStatsData,
    AttributeBlock,
    # Combat
    CombatData,
    DamageType,
    CombatState,
    # Inventory
    ContainerData,
    EquipmentSlotsData,
    ItemData,
    WeaponData,
    ArmorData,
    ConsumableData,
    EquipmentSlot,
    ItemType,
    # AI
    AIData,
    StaticAIData,
    DynamicAIData,
    DialogueData,
    BehaviorType,
    CombatStyle,
    PersonalityTrait,
    # Player
    PlayerConnectionData,
    PlayerProgressData,
    QuestLogData,
    # Portal
    PortalData,
    InstanceData,
)

# Systems process entities with specific components each tick
from .systems import (
    MovementSystem,
    MovementRequestData,
    create_movement_request,
    CombatSystem,
    CombatInitiationSystem,
    CombatEvent,
    AttackRequestData,
    RegenerationSystem,
    DeathSystem,
    RespawnSystem,
)

# World loading
from .world import (
    WorldLoader,
    load_world,
    TemplateRegistry,
    RoomTemplate,
    MobTemplate,
    ItemTemplate,
    PortalTemplate,
    EntityFactory,
)

# Command system
from .commands import (
    CommandParser,
    ParsedCommand,
    CommandRegistry,
    command,
    get_command_registry,
    CommandHandler,
)

__all__ = [
    # Components
    "IdentityData",
    "StaticIdentityData",
    "DynamicIdentityData",
    "LocationData",
    "RoomData",
    "StaticRoomData",
    "DynamicRoomData",
    "ExitData",
    "StatsData",
    "PlayerStatsData",
    "MobStatsData",
    "AttributeBlock",
    "CombatData",
    "DamageType",
    "CombatState",
    "ContainerData",
    "EquipmentSlotsData",
    "ItemData",
    "WeaponData",
    "ArmorData",
    "ConsumableData",
    "EquipmentSlot",
    "ItemType",
    "AIData",
    "StaticAIData",
    "DynamicAIData",
    "DialogueData",
    "BehaviorType",
    "CombatStyle",
    "PersonalityTrait",
    "PlayerConnectionData",
    "PlayerProgressData",
    "QuestLogData",
    "PortalData",
    "InstanceData",
    # Systems
    "MovementSystem",
    "MovementRequestData",
    "create_movement_request",
    "CombatSystem",
    "CombatInitiationSystem",
    "CombatEvent",
    "AttackRequestData",
    "RegenerationSystem",
    "DeathSystem",
    "RespawnSystem",
    # World
    "WorldLoader",
    "load_world",
    "TemplateRegistry",
    "RoomTemplate",
    "MobTemplate",
    "ItemTemplate",
    "PortalTemplate",
    "EntityFactory",
    # Commands
    "CommandParser",
    "ParsedCommand",
    "CommandRegistry",
    "command",
    "get_command_registry",
    "CommandHandler",
]
