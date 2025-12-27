"""
Game Systems

Systems process entities with specific component combinations each tick.
They read from snapshots (for consistency) and write to WriteBuffer
(for atomic commits).

System execution order (by priority):
- 5: LevelingSystem - Process level-up requests
- 10: WeatherSystem - Update weather conditions
- 10: MovementSystem - Room transitions
- 20: CombatInitiationSystem - Start combat from requests
- 30: CombatSystem - Process attacks and damage
- 40: DeathSystem - Handle entity death
- 50: RespawnSystem - Spawn mobs/items in rooms
- 60: RegenerationSystem - HP/mana/stamina regen
- 70: ShopRestockSystem - Restock shop inventories
- 75: TradeCleanupSystem - Clean up expired trades
- 94: WaypointDiscoverySystem - Detect waypoint discoveries
- 95: JourneyTrackingSystem - Track journey fatigue/morale
- 96: SupplyConsumptionSystem - Auto-consume food/water
- 97: MountStaminaSystem - Mount stamina recovery

Utility Systems (not tick-based):
- GuildAccessSystem - Validates guild room access by class
"""

from .movement import MovementSystem, MovementRequestData, create_movement_request
from .combat import (
    CombatSystem,
    CombatInitiationSystem,
    CombatEvent,
    AttackRequestData,
)
from .regeneration import (
    RegenerationSystem,
    DeathSystem,
    RespawnSystem,
)
from .shop import (
    ShopRestockSystem,
    TradeCleanupSystem,
)
from .journey import (
    JourneyTrackingSystem,
    SupplyConsumptionSystem,
    MountStaminaSystem,
    WeatherSystem,
    WaypointDiscoverySystem,
    MovementCostCalculator,
    JourneyEventGenerator,
)
from .group import (
    GroupExpShareSystem,
    FollowSystem,
    GroupCombatSystem,
    GroupInviteCleanupSystem,
    handle_mob_death_exp,
)
from .world import (
    WorldTimeSystem,
    WorldEventSystem,
    AnnouncementSystem,
    ZonePopulationSystem,
    get_world_state,
    initialize_world_state,
)
from .quests import (
    QuestProgressSystem,
    QuestExpirationSystem,
    QuestRewardSystem,
    get_quest_reward_system,
    accept_quest,
    turn_in_quest,
    get_available_quests,
)
from .leveling import (
    LevelingSystem,
    get_leveling_system,
    start_leveling_system,
    leveling_system_exists,
)
from .guild_access import (
    GuildAccessSystem,
    get_guild_access_system,
    start_guild_access_system,
    guild_access_system_exists,
    can_enter_guild_room,
)

__all__ = [
    # Movement
    "MovementSystem",
    "MovementRequestData",
    "create_movement_request",
    # Combat
    "CombatSystem",
    "CombatInitiationSystem",
    "CombatEvent",
    "AttackRequestData",
    # Regeneration & Life cycle
    "RegenerationSystem",
    "DeathSystem",
    "RespawnSystem",
    # Economy
    "ShopRestockSystem",
    "TradeCleanupSystem",
    # Journey
    "JourneyTrackingSystem",
    "SupplyConsumptionSystem",
    "MountStaminaSystem",
    "WeatherSystem",
    "WaypointDiscoverySystem",
    "MovementCostCalculator",
    "JourneyEventGenerator",
    # Group
    "GroupExpShareSystem",
    "FollowSystem",
    "GroupCombatSystem",
    "GroupInviteCleanupSystem",
    "handle_mob_death_exp",
    # World
    "WorldTimeSystem",
    "WorldEventSystem",
    "AnnouncementSystem",
    "ZonePopulationSystem",
    "get_world_state",
    "initialize_world_state",
    # Quests
    "QuestProgressSystem",
    "QuestExpirationSystem",
    "QuestRewardSystem",
    "get_quest_reward_system",
    "accept_quest",
    "turn_in_quest",
    "get_available_quests",
    # Leveling
    "LevelingSystem",
    "get_leveling_system",
    "start_leveling_system",
    "leveling_system_exists",
    # Guild Access
    "GuildAccessSystem",
    "get_guild_access_system",
    "start_guild_access_system",
    "guild_access_system_exists",
    "can_enter_guild_room",
]
