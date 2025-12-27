"""Quest tracking and management systems."""

from datetime import datetime
from typing import Dict, List, Optional

from core.system import System


class QuestProgressSystem(System):
    """
    Tracks quest progress based on game events.

    Listens for kills, item pickups, room entries, etc. and updates
    quest objectives accordingly.
    """

    priority = 85  # Run after combat, movement systems

    required_components = ["QuestLogData"]

    async def process(self, entity_id: str, components: Dict) -> None:
        """Process quest progress updates."""
        # This system primarily responds to events rather than ticking
        pass

    async def on_mob_killed(
        self,
        player_id: str,
        mob_template_id: str,
        zone_id: str,
        game_state,
    ) -> List[str]:
        """
        Handle mob kill event for quest progress.

        Returns list of quest IDs that had objectives completed.
        """
        from ..components.quests import QuestLogData, QuestState

        quest_log = await game_state.get_component(player_id, "QuestLogData")
        if not quest_log:
            return []

        updated_quests = []

        for quest_id, active in quest_log.active_quests.items():
            if active.state != QuestState.ACTIVE:
                continue

            completed_objs = active.update_kill_progress(mob_template_id, zone_id)
            if completed_objs:
                updated_quests.append(quest_id)

                # Check if quest is now fully complete
                if active.is_complete:
                    active.state = QuestState.COMPLETED

        if updated_quests:
            await game_state.set_component(player_id, "QuestLogData", quest_log)

        return updated_quests

    async def on_item_collected(
        self,
        player_id: str,
        item_id: str,
        count: int,
        game_state,
    ) -> List[str]:
        """
        Handle item collection for quest progress.

        Returns list of quest IDs that had objectives completed.
        """
        from ..components.quests import QuestLogData, QuestState

        quest_log = await game_state.get_component(player_id, "QuestLogData")
        if not quest_log:
            return []

        updated_quests = []

        for quest_id, active in quest_log.active_quests.items():
            if active.state != QuestState.ACTIVE:
                continue

            completed_objs = active.update_collect_progress(item_id, count)
            if completed_objs:
                updated_quests.append(quest_id)

                if active.is_complete:
                    active.state = QuestState.COMPLETED

        if updated_quests:
            await game_state.set_component(player_id, "QuestLogData", quest_log)

        return updated_quests

    async def on_room_entered(
        self,
        player_id: str,
        room_id: str,
        game_state,
    ) -> List[str]:
        """
        Handle room entry for explore quest progress.

        Returns list of quest IDs that had objectives completed.
        """
        from ..components.quests import QuestLogData, QuestState

        quest_log = await game_state.get_component(player_id, "QuestLogData")
        if not quest_log:
            return []

        updated_quests = []

        for quest_id, active in quest_log.active_quests.items():
            if active.state != QuestState.ACTIVE:
                continue

            completed_objs = active.update_explore_progress(room_id)
            if completed_objs:
                updated_quests.append(quest_id)

                if active.is_complete:
                    active.state = QuestState.COMPLETED

        if updated_quests:
            await game_state.set_component(player_id, "QuestLogData", quest_log)

        return updated_quests

    async def on_npc_talk(
        self,
        player_id: str,
        npc_id: str,
        game_state,
    ) -> List[str]:
        """
        Handle talking to NPC for quest progress.

        Returns list of quest IDs that had objectives completed.
        """
        from ..components.quests import QuestLogData, QuestState

        quest_log = await game_state.get_component(player_id, "QuestLogData")
        if not quest_log:
            return []

        updated_quests = []

        for quest_id, active in quest_log.active_quests.items():
            if active.state != QuestState.ACTIVE:
                continue

            completed_objs = active.update_talk_progress(npc_id)
            if completed_objs:
                updated_quests.append(quest_id)

                if active.is_complete:
                    active.state = QuestState.COMPLETED

        if updated_quests:
            await game_state.set_component(player_id, "QuestLogData", quest_log)

        return updated_quests


class QuestExpirationSystem(System):
    """
    Checks for expired quests and fails them.

    Runs periodically to check time-limited quests.
    """

    priority = 90

    required_components = ["QuestLogData"]

    async def process(self, entity_id: str, components: Dict) -> None:
        """Check for and fail expired quests."""
        from ..components.quests import QuestLogData, QuestState

        quest_log: QuestLogData = components["QuestLogData"]
        now = datetime.utcnow()

        expired_quests = []

        for quest_id, active in quest_log.active_quests.items():
            if active.state != QuestState.ACTIVE:
                continue

            if active.is_expired:
                expired_quests.append(quest_id)

        # Process expirations
        for quest_id in expired_quests:
            quest_log.fail_quest(quest_id)
            # Would send notification to player here


class QuestRewardSystem:
    """
    Handles distributing quest rewards.

    Not a tick-based system, called when quests are turned in.
    """

    async def grant_rewards(
        self,
        player_id: str,
        quest_id: str,
        game_state,
    ) -> Dict:
        """
        Grant rewards for completing a quest.

        Returns dict with granted rewards info.
        """
        from ..components.quests import (
            get_quest_definition,
            QuestLogData,
        )
        from ..components.stats import PlayerStatsData
        from ..components.inventory import ContainerData

        definition = get_quest_definition(quest_id)
        if not definition:
            return {"error": "Quest not found"}

        quest_log = await game_state.get_component(player_id, "QuestLogData")
        if not quest_log:
            return {"error": "No quest log"}

        if quest_id not in quest_log.active_quests:
            return {"error": "Quest not active"}

        active = quest_log.active_quests[quest_id]
        if not active.is_complete:
            return {"error": "Quest not complete"}

        rewards = definition.rewards
        granted = {
            "experience": 0,
            "gold": 0,
            "items": [],
            "reputation": {},
            "unlocked_quests": [],
        }

        # Grant experience
        if rewards.experience > 0:
            stats = await game_state.get_component(player_id, "PlayerStatsData")
            if stats:
                stats.experience += rewards.experience
                granted["experience"] = rewards.experience
                await game_state.set_component(player_id, "PlayerStatsData", stats)

        # Grant gold
        if rewards.gold > 0:
            stats = await game_state.get_component(player_id, "PlayerStatsData")
            if stats:
                stats.gold = getattr(stats, "gold", 0) + rewards.gold
                granted["gold"] = rewards.gold
                await game_state.set_component(player_id, "PlayerStatsData", stats)

        # Grant items
        if rewards.items:
            inventory = await game_state.get_component(player_id, "ContainerData")
            if inventory:
                for item_template_id in rewards.items:
                    # Would use EntityFactory to create item
                    granted["items"].append(item_template_id)

        # Grant reputation
        if rewards.reputation:
            # Would update reputation component
            granted["reputation"] = rewards.reputation

        # Unlock follow-up quests
        if rewards.unlocks_quests:
            for unlock_id in rewards.unlocks_quests:
                quest_log.discover_quest(unlock_id)
                granted["unlocked_quests"].append(unlock_id)

        # Complete the quest in log
        quest_log.complete_quest(quest_id)

        # Set repeatable cooldown if applicable
        if definition.is_repeatable:
            quest_log.set_repeatable_cooldown(
                quest_id, definition.repeatable_cooldown_hours
            )

        await game_state.set_component(player_id, "QuestLogData", quest_log)

        return granted


# Singleton instance
_quest_reward_system = QuestRewardSystem()


def get_quest_reward_system() -> QuestRewardSystem:
    """Get the quest reward system instance."""
    return _quest_reward_system


async def accept_quest(
    player_id: str,
    quest_id: str,
    game_state,
) -> tuple[bool, str]:
    """
    Have a player accept a quest.

    Returns (success, message).
    """
    from ..components.quests import (
        get_quest_definition,
        check_quest_requirements,
        QuestLogData,
    )
    from ..components.stats import PlayerStatsData
    from ..components.character import ClassData, RaceData

    definition = get_quest_definition(quest_id)
    if not definition:
        return False, "Quest not found."

    # Get player info
    stats = await game_state.get_component(player_id, "PlayerStatsData")
    if not stats:
        return False, "Cannot access player data."

    class_data = await game_state.get_component(player_id, "ClassData")
    race_data = await game_state.get_component(player_id, "RaceData")

    player_class = class_data.class_id if class_data else None
    player_race = race_data.race_id if race_data else None

    # Get quest log
    quest_log = await game_state.get_component(player_id, "QuestLogData")
    if not quest_log:
        quest_log = QuestLogData()

    # Check requirements
    can_accept, reason = check_quest_requirements(
        definition,
        player_level=stats.level,
        player_class=player_class,
        player_race=player_race,
        completed_quests=quest_log.completed_quests,
    )

    if not can_accept:
        return False, reason

    # Accept the quest
    active = quest_log.accept_quest(definition)
    if not active:
        if quest_log.has_quest(quest_id):
            return False, "You already have this quest."
        if not quest_log.can_accept_quest:
            return False, "Your quest log is full."
        return False, "Cannot accept this quest."

    await game_state.set_component(player_id, "QuestLogData", quest_log)

    return True, f"Quest accepted: {definition.name}"


async def turn_in_quest(
    player_id: str,
    quest_id: str,
    game_state,
) -> tuple[bool, str, Dict]:
    """
    Turn in a completed quest for rewards.

    Returns (success, message, rewards).
    """
    from ..components.quests import get_quest_definition, QuestLogData, QuestState

    definition = get_quest_definition(quest_id)
    if not definition:
        return False, "Quest not found.", {}

    quest_log = await game_state.get_component(player_id, "QuestLogData")
    if not quest_log:
        return False, "No quest log.", {}

    if quest_id not in quest_log.active_quests:
        return False, "You don't have this quest.", {}

    active = quest_log.active_quests[quest_id]
    if active.state != QuestState.COMPLETED:
        if not active.is_complete:
            return False, "Quest objectives not complete.", {}

    # Grant rewards
    reward_system = get_quest_reward_system()
    granted = await reward_system.grant_rewards(player_id, quest_id, game_state)

    if "error" in granted:
        return False, granted["error"], {}

    # Build reward message
    reward_lines = []
    if granted["experience"]:
        reward_lines.append(f"{granted['experience']} experience")
    if granted["gold"]:
        reward_lines.append(f"{granted['gold']} gold")
    if granted["items"]:
        reward_lines.append(f"{len(granted['items'])} item(s)")

    reward_text = ", ".join(reward_lines) if reward_lines else "no rewards"

    return True, f"Quest complete! You receive: {reward_text}", granted


async def get_available_quests(
    player_id: str,
    npc_id: str,
    game_state,
) -> List:
    """
    Get quests available from an NPC for a player.

    Returns list of (QuestDefinition, can_accept, reason) tuples.
    """
    from ..components.quests import (
        get_quests_by_giver,
        check_quest_requirements,
        QuestLogData,
    )
    from ..components.stats import PlayerStatsData
    from ..components.character import ClassData, RaceData

    quests_from_npc = get_quests_by_giver(npc_id)
    if not quests_from_npc:
        return []

    # Get player info
    stats = await game_state.get_component(player_id, "PlayerStatsData")
    quest_log = await game_state.get_component(player_id, "QuestLogData")
    class_data = await game_state.get_component(player_id, "ClassData")
    race_data = await game_state.get_component(player_id, "RaceData")

    if not stats:
        return []

    if not quest_log:
        quest_log = QuestLogData()

    player_class = class_data.class_id if class_data else None
    player_race = race_data.race_id if race_data else None

    results = []

    for definition in quests_from_npc:
        # Skip if already have or completed (unless repeatable)
        if quest_log.has_quest(definition.quest_id):
            continue

        if quest_log.has_completed(definition.quest_id):
            if not definition.is_repeatable:
                continue
            if not quest_log.can_repeat(definition.quest_id):
                continue

        # Skip hidden quests unless player discovered them
        if definition.is_hidden:
            if definition.quest_id not in quest_log.discovered_quests:
                continue

        # Check requirements
        can_accept, reason = check_quest_requirements(
            definition,
            player_level=stats.level,
            player_class=player_class,
            player_race=player_race,
            completed_quests=quest_log.completed_quests,
        )

        results.append((definition, can_accept, reason))

    return results
