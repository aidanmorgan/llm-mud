"""
Quest Generation Bridge System

Connects the QuestGenerator Ray actor to the game's quest system.
Handles context building, conversion from LLM output to game structures,
and instanced entity spawning.
"""

import logging
from copy import deepcopy
from datetime import datetime
from typing import Optional, List, Dict, Any, Tuple

from llm.schemas import (
    GeneratedQuest,
    GeneratedObjective,
    GeneratedReward,
    QuestGenerationContext,
    QuestArchetype,
    ZoneQuestTheme,
    ZoneType,
    ZONE_QUEST_PREFERENCES,
)

from ..components.quests import (
    QuestDefinition,
    QuestObjective,
    QuestReward,
    QuestRarity,
    ObjectiveType,
    register_quest,
    get_quest_definition,
)
from ..components.quest_instance import (
    QuestInstanceData,
    QuestSpawnedEntityData,
    GeneratedQuestData,
)

logger = logging.getLogger(__name__)

# =============================================================================
# Conversion: LLM Output -> Game Structures
# =============================================================================

# Map LLM objective types to game ObjectiveType
OBJECTIVE_TYPE_MAP: Dict[str, ObjectiveType] = {
    "kill": ObjectiveType.KILL,
    "collect": ObjectiveType.COLLECT,
    "deliver": ObjectiveType.DELIVER,
    "explore": ObjectiveType.EXPLORE,
    "talk": ObjectiveType.TALK,
    "use": ObjectiveType.USE,
    "escort": ObjectiveType.ESCORT,
    "defend": ObjectiveType.DEFEND,
}

# Map LLM rarity to game QuestRarity
RARITY_MAP: Dict[str, QuestRarity] = {
    "common": QuestRarity.COMMON,
    "uncommon": QuestRarity.UNCOMMON,
    "rare": QuestRarity.RARE,
    "epic": QuestRarity.EPIC,
    "legendary": QuestRarity.LEGENDARY,
}


def convert_objective(
    llm_obj: GeneratedObjective,
    index: int,
) -> QuestObjective:
    """Convert LLM GeneratedObjective to game QuestObjective."""
    obj_type = OBJECTIVE_TYPE_MAP.get(
        llm_obj.objective_type, ObjectiveType.KILL
    )

    return QuestObjective(
        objective_id=f"obj_{index}",
        objective_type=obj_type,
        description=llm_obj.description,
        target_id=llm_obj.target_type_hint,
        target_name=llm_obj.target_description,
        required_count=llm_obj.required_count,
        zone_id=llm_obj.location_hint,
    )


def convert_rewards(llm_rewards: GeneratedReward) -> QuestReward:
    """Convert LLM GeneratedReward to game QuestReward."""
    reputation = {}
    if llm_rewards.reputation_faction and llm_rewards.reputation_amount:
        reputation[llm_rewards.reputation_faction] = llm_rewards.reputation_amount

    return QuestReward(
        experience=llm_rewards.experience,
        gold=llm_rewards.gold,
        items=llm_rewards.item_hints,  # These are hints, would need item generation
        reputation=reputation,
    )


def convert_generated_to_definition(
    generated: GeneratedQuest,
    giver_id: str,
    zone_id: str,
    player_level: int,
) -> QuestDefinition:
    """
    Convert LLM GeneratedQuest to game QuestDefinition.

    Args:
        generated: The LLM-generated quest
        giver_id: NPC entity ID giving the quest
        zone_id: Zone where the quest takes place
        player_level: Player's level (for scaling)

    Returns:
        QuestDefinition ready to be registered
    """
    # Generate unique quest ID
    import hashlib
    hash_input = f"{zone_id}:{generated.name}:{datetime.utcnow().timestamp()}"
    quest_hash = hashlib.md5(hash_input.encode()).hexdigest()[:8]
    quest_id = f"gen_{zone_id}_{quest_hash}"

    # Convert objectives
    objectives = [
        convert_objective(obj, i)
        for i, obj in enumerate(generated.objectives)
    ]

    # Convert rewards
    rewards = convert_rewards(generated.rewards)

    # Convert rarity
    rarity = RARITY_MAP.get(generated.rarity.value, QuestRarity.COMMON)

    # Level range based on player level
    min_level = max(1, player_level - 3)
    max_level = min(50, player_level + 5)

    return QuestDefinition(
        quest_id=quest_id,
        name=generated.name,
        description=generated.description,
        rarity=rarity,
        min_level=min_level,
        max_level=max_level,
        giver_id=giver_id,
        giver_zone=zone_id,
        objectives=objectives,
        rewards=rewards,
        intro_text=generated.intro_text,
        progress_text=generated.progress_text,
        complete_text=generated.complete_text,
        is_chain_quest=generated.is_chain_quest,
        chain_order=generated.chain_position if generated.is_chain_quest else 0,
    )


# =============================================================================
# Context Building
# =============================================================================


def infer_zone_type(zone_id: str, zone_description: str = "") -> ZoneType:
    """Infer zone type from zone ID and description."""
    zone_lower = zone_id.lower() + " " + zone_description.lower()

    if any(word in zone_lower for word in ["city", "town", "village", "market"]):
        return ZoneType.CITY
    if any(word in zone_lower for word in ["forest", "wood", "grove", "glade"]):
        return ZoneType.FOREST
    if any(word in zone_lower for word in ["dungeon", "cave", "mine", "crypt"]):
        return ZoneType.DUNGEON
    if any(word in zone_lower for word in ["swamp", "marsh", "bog", "mire"]):
        return ZoneType.SWAMP
    if any(word in zone_lower for word in ["mountain", "peak", "cliff", "highland"]):
        return ZoneType.MOUNTAIN
    if any(word in zone_lower for word in ["ruin", "ancient", "temple", "tomb"]):
        return ZoneType.RUINS
    if any(word in zone_lower for word in ["coast", "beach", "sea", "harbor", "port"]):
        return ZoneType.COASTAL
    if any(word in zone_lower for word in ["underground", "deep", "cavern"]):
        return ZoneType.UNDERGROUND
    if any(word in zone_lower for word in ["volcano", "lava", "fire", "ash"]):
        return ZoneType.VOLCANIC
    if any(word in zone_lower for word in ["frozen", "ice", "snow", "frost"]):
        return ZoneType.FROZEN

    # Default to forest
    return ZoneType.FOREST


async def build_quest_context(
    player_id: str,
    npc_id: str,
    zone_id: str,
    game_state,
    npc_dialogue=None,
) -> Optional[QuestGenerationContext]:
    """
    Build QuestGenerationContext from game state.

    Args:
        player_id: The player requesting a quest
        npc_id: The quest-giving NPC
        zone_id: Zone where quest originates
        game_state: GameState actor reference
        npc_dialogue: Optional pre-fetched DialogueData

    Returns:
        QuestGenerationContext for LLM generation
    """
    from ..components.stats import PlayerStatsData
    from ..components.character import ClassData, RaceData
    from ..components.quests import QuestLogData
    from ..components.identity import IdentityData
    from ..components.ai import DialogueData
    from ..components.world import ZoneStateData

    # Get player info
    stats = await game_state.get_component(player_id, "PlayerStatsData")
    if not stats:
        logger.warning(f"No stats for player {player_id}")
        return None

    class_data = await game_state.get_component(player_id, "ClassData")
    race_data = await game_state.get_component(player_id, "RaceData")
    quest_log = await game_state.get_component(player_id, "QuestLogData")

    player_class = class_data.class_id if class_data else "adventurer"
    player_race = race_data.race_id if race_data else "human"

    # Get NPC info
    if not npc_dialogue:
        npc_dialogue = await game_state.get_component(npc_id, "DialogueData")

    npc_identity = await game_state.get_component(npc_id, "IdentityData")
    npc_name = npc_identity.name if npc_identity else "Quest Giver"

    # Get zone info
    zone_state = await game_state.get_component(zone_id, "ZoneStateData")
    zone_name = zone_state.zone_name if zone_state else zone_id
    zone_description = zone_state.description if zone_state else ""

    # Infer zone type
    zone_type = infer_zone_type(zone_id, zone_description)

    # Get preferred archetypes for zone
    preferred = ZONE_QUEST_PREFERENCES.get(
        zone_type.value,
        [QuestArchetype.COMBAT, QuestArchetype.EXPLORATION]
    )

    # Override with NPC preferences if set
    if npc_dialogue and npc_dialogue.preferred_quest_types:
        preferred = [
            QuestArchetype(t) for t in npc_dialogue.preferred_quest_types
            if t in [a.value for a in QuestArchetype]
        ] or preferred

    # Build zone theme
    zone_theme = ZoneQuestTheme(
        zone_id=zone_id,
        zone_type=zone_type,
        zone_name=zone_name,
        preferred_archetypes=preferred,
        flavor_vocabulary=[],  # Would be loaded from zone config
        local_factions=[npc_dialogue.quest_faction] if npc_dialogue and npc_dialogue.quest_faction else [],
        neighboring_zones=npc_dialogue.quest_zones if npc_dialogue else [],
        zone_description=zone_description,
    )

    # Get recent quest types for variety
    recent_types = []
    if quest_log:
        # Look at most recent 5 completed quests
        for quest_id in list(quest_log.completed_quests.keys())[-5:]:
            quest_def = get_quest_definition(quest_id)
            # Would need to track archetype in quest - for now skip
            pass

    # Get available targets in zone (level-appropriate)
    # These would come from zone mob/item/location registries
    available_mobs = []  # Would query template registry for zone mobs
    available_locations = []  # Would query room templates
    available_npcs = []  # Would query NPC templates

    return QuestGenerationContext(
        player_level=stats.level,
        player_class=player_class,
        player_race=player_race,
        zone_theme=zone_theme,
        target_zone_id=zone_id,
        target_zone_name=zone_name,
        target_zone_description=zone_description,
        giver_name=npc_name,
        giver_role=npc_dialogue.quest_personality if npc_dialogue else "quest giver",
        giver_personality=npc_dialogue.quest_personality if npc_dialogue else None,
        giver_faction=npc_dialogue.quest_faction if npc_dialogue else None,
        recent_quest_types=recent_types,
        player_active_quest_count=quest_log.active_count if quest_log else 0,
        completed_quest_count=len(quest_log.completed_quests) if quest_log else 0,
        available_mob_types=available_mobs,
        available_locations=available_locations,
        available_npcs=available_npcs,
    )


# =============================================================================
# Quest Generator Integration
# =============================================================================


def get_quest_generator():
    """Get the QuestGenerator Ray actor if available."""
    try:
        from generation.quest import get_quest_generator, quest_generator_exists
        if quest_generator_exists():
            return get_quest_generator()
    except ImportError:
        logger.debug("Quest generation package not available")
    except Exception as e:
        logger.warning(f"Failed to get quest generator: {e}")
    return None


async def generate_quest_for_npc(
    player_id: str,
    npc_id: str,
    zone_id: str,
    game_state,
    force_generate: bool = False,
) -> Optional[Tuple[QuestDefinition, GeneratedQuest]]:
    """
    Generate a dynamic quest from an NPC for a player.

    Args:
        player_id: Player requesting the quest
        npc_id: NPC offering the quest
        zone_id: Zone for the quest
        game_state: GameState actor
        force_generate: Skip pool, generate fresh

    Returns:
        Tuple of (QuestDefinition, raw GeneratedQuest) or None
    """
    from ..components.ai import DialogueData
    from ..components.stats import PlayerStatsData

    # Check if NPC can generate quests
    dialogue = await game_state.get_component(npc_id, "DialogueData")
    if not dialogue or not getattr(dialogue, "can_generate_quests", False):
        logger.debug(f"NPC {npc_id} cannot generate quests")
        return None

    # Get generator
    generator = get_quest_generator()
    if not generator:
        logger.debug("Quest generator not available")
        return None

    # Build context
    context = await build_quest_context(
        player_id, npc_id, zone_id, game_state, dialogue
    )
    if not context:
        logger.warning("Failed to build quest context")
        return None

    # Get player level for conversion
    stats = await game_state.get_component(player_id, "PlayerStatsData")
    player_level = stats.level if stats else 1

    try:
        # Call Ray actor
        import ray
        generated = await generator.get_quest.remote(context, force_generate)

        if not generated:
            logger.debug("Generator returned no quest")
            return None

        # Convert to game definition
        definition = convert_generated_to_definition(
            generated, npc_id, zone_id, player_level
        )

        # Register temporarily so it can be accepted
        register_quest(definition)

        logger.info(f"Generated quest '{definition.name}' for player {player_id}")

        return (definition, generated)

    except Exception as e:
        logger.error(f"Quest generation failed: {e}")
        return None


async def get_generated_quests_for_player(
    player_id: str,
    npc_id: str,
    zone_id: str,
    game_state,
    max_quests: int = 3,
) -> List[Tuple[QuestDefinition, bool, str]]:
    """
    Get available generated quests from an NPC, same format as static quests.

    Returns list of (QuestDefinition, can_accept, reason) tuples.
    """
    from ..components.quests import QuestLogData, check_quest_requirements
    from ..components.stats import PlayerStatsData
    from ..components.character import ClassData, RaceData

    results = []

    # Generate up to max_quests
    for _ in range(max_quests):
        result = await generate_quest_for_npc(
            player_id, npc_id, zone_id, game_state
        )

        if not result:
            break

        definition, _ = result

        # Check requirements
        stats = await game_state.get_component(player_id, "PlayerStatsData")
        quest_log = await game_state.get_component(player_id, "QuestLogData")
        class_data = await game_state.get_component(player_id, "ClassData")
        race_data = await game_state.get_component(player_id, "RaceData")

        if not stats:
            break

        player_class = class_data.class_id if class_data else None
        player_race = race_data.race_id if race_data else None

        can_accept, reason = check_quest_requirements(
            definition,
            player_level=stats.level,
            player_class=player_class,
            player_race=player_race,
            completed_quests=quest_log.completed_quests if quest_log else {},
        )

        results.append((definition, can_accept, reason))

    return results


# =============================================================================
# Instanced Spawn Management
# =============================================================================


async def spawn_quest_entities(
    player_id: str,
    quest_id: str,
    generated: GeneratedQuest,
    game_state,
) -> List[str]:
    """
    Spawn instanced entities for a quest's objectives.

    Args:
        player_id: Player who owns the quest
        quest_id: The quest ID
        generated: The raw generated quest with spawn info
        game_state: GameState actor

    Returns:
        List of spawned entity IDs
    """
    from ..components.group import GroupMembershipData

    spawned_ids = []

    # Get player's group for visibility
    group_membership = await game_state.get_component(player_id, "GroupMembershipData")
    visible_to = {player_id}

    if group_membership and group_membership.group_id:
        # Would add group members to visible_to
        pass

    for obj in generated.objectives:
        if not obj.instanced_spawns:
            continue

        for spawn in obj.instanced_spawns:
            # Would use EntityFactory to create entity based on spawn info
            # For now, just log what would be spawned
            logger.info(
                f"Would spawn {spawn.spawn_type} '{spawn.template_hint}' "
                f"at '{spawn.spawn_location_hint}' for quest {quest_id}"
            )

            # Entity creation would happen here:
            # entity_id = await factory.create_instanced_entity(
            #     spawn_type=spawn.spawn_type,
            #     template_hint=spawn.template_hint,
            #     location_hint=spawn.spawn_location_hint,
            #     custom_name=spawn.custom_name,
            #     custom_description=spawn.custom_description,
            # )
            #
            # # Attach QuestInstanceData
            # instance_data = QuestInstanceData(
            #     quest_id=quest_id,
            #     visible_to=visible_to,
            #     group_visible=True,
            #     is_quest_target=spawn.is_quest_target,
            #     spawned_by=player_id,
            # )
            # await game_state.set_component(entity_id, "QuestInstanceData", instance_data)
            #
            # spawned_ids.append(entity_id)

    # Track spawned entities on player
    if spawned_ids:
        spawn_tracker = await game_state.get_component(player_id, "QuestSpawnedEntityData")
        if not spawn_tracker:
            spawn_tracker = QuestSpawnedEntityData()

        for eid in spawned_ids:
            spawn_tracker.add_spawned(quest_id, eid)

        await game_state.set_component(player_id, "QuestSpawnedEntityData", spawn_tracker)

    return spawned_ids


async def cleanup_quest_entities(
    player_id: str,
    quest_id: str,
    game_state,
    reason: str = "complete",
) -> int:
    """
    Clean up instanced entities when quest ends.

    Args:
        player_id: Player who owned the quest
        quest_id: The quest being cleaned up
        game_state: GameState actor
        reason: "complete", "abandon", or "fail"

    Returns:
        Number of entities removed
    """
    spawn_tracker = await game_state.get_component(player_id, "QuestSpawnedEntityData")
    if not spawn_tracker:
        return 0

    entity_ids = spawn_tracker.remove_spawned(quest_id)
    if not entity_ids:
        return 0

    removed = 0
    for entity_id in entity_ids:
        instance_data = await game_state.get_component(entity_id, "QuestInstanceData")
        if not instance_data:
            continue

        # Check if should despawn based on reason
        should_despawn = False
        if reason == "complete" and instance_data.despawn_on_quest_complete:
            should_despawn = True
        elif reason == "abandon" and instance_data.despawn_on_quest_abandon:
            should_despawn = True
        elif reason == "fail" and instance_data.despawn_on_quest_fail:
            should_despawn = True

        if should_despawn:
            # Would destroy entity here
            # await game_state.destroy_entity(entity_id)
            logger.info(f"Would despawn entity {entity_id} for quest {quest_id}")
            removed += 1

    await game_state.set_component(player_id, "QuestSpawnedEntityData", spawn_tracker)

    return removed
