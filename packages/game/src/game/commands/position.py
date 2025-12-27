"""
Position Commands

Commands for changing the player's physical position (standing, sitting, resting, sleeping).
Position affects regeneration rates and command availability.
"""

from typing import List

from core import EntityId
from core.component import get_component_actor
from .registry import command, CommandCategory
from ..components.position import Position


# =============================================================================
# Position Commands
# =============================================================================


@command(
    name="stand",
    aliases=["wake", "st"],
    category=CommandCategory.MOVEMENT,
    help_text="Stand up from sitting, resting, or sleeping.",
    usage="stand",
    min_position=Position.SLEEPING,
)
async def cmd_stand(player_id: EntityId, args: List[str]) -> str:
    """Stand up."""

    position_actor = get_component_actor("Position")
    position_data = await position_actor.get.remote(player_id)

    if not position_data:
        # Create default position data if it doesn't exist
        from game.components.position import PositionData

        position_data = PositionData()
        await position_actor.set.remote(player_id, position_data)
        return "You are already standing."

    if position_data.position == Position.STANDING:
        return "You are already standing."

    if position_data.position == Position.DEAD:
        return "You can't do that while dead."

    old_position = position_data.position

    def do_stand(p):
        p.stand()

    await position_actor.mutate.remote(player_id, do_stand)

    if old_position == Position.SLEEPING:
        return "You wake and stand up."
    elif old_position == Position.RESTING:
        return "You stop resting and stand up."
    elif old_position == Position.SITTING:
        return "You stand up."
    else:
        return "You stand up."


@command(
    name="sit",
    category=CommandCategory.MOVEMENT,
    help_text="Sit down. Slightly increases regeneration rate.",
    usage="sit",
    min_position=Position.SLEEPING,
)
async def cmd_sit(player_id: EntityId, args: List[str]) -> str:
    """Sit down."""

    # Check if in combat
    combat_actor = get_component_actor("Combat")
    combat_data = await combat_actor.get.remote(player_id)

    if combat_data and combat_data.is_in_combat:
        return "You can't sit down while fighting!"

    position_actor = get_component_actor("Position")
    position_data = await position_actor.get.remote(player_id)

    if not position_data:
        from game.components.position import PositionData

        position_data = PositionData()

    if position_data.position == Position.SITTING:
        return "You are already sitting."

    if position_data.position == Position.DEAD:
        return "You can't do that while dead."

    def do_sit(p):
        p.sit()

    await position_actor.mutate.remote(player_id, do_sit)

    if position_data.position == Position.SLEEPING:
        return "You wake up and sit."
    else:
        return "You sit down."


@command(
    name="rest",
    category=CommandCategory.MOVEMENT,
    help_text="Rest to recover health, mana, and stamina faster.",
    usage="rest",
    min_position=Position.SLEEPING,
)
async def cmd_rest(player_id: EntityId, args: List[str]) -> str:
    """Start resting for faster regeneration."""

    # Check if in combat
    combat_actor = get_component_actor("Combat")
    combat_data = await combat_actor.get.remote(player_id)

    if combat_data and combat_data.is_in_combat:
        return "You can't rest while fighting!"

    position_actor = get_component_actor("Position")
    position_data = await position_actor.get.remote(player_id)

    if not position_data:
        from game.components.position import PositionData

        position_data = PositionData()

    if position_data.position == Position.RESTING:
        return "You are already resting."

    if position_data.position == Position.DEAD:
        return "You can't do that while dead."

    def do_rest(p):
        p.rest()

    await position_actor.mutate.remote(player_id, do_rest)

    if position_data.position == Position.SLEEPING:
        return "You wake up and start resting."
    else:
        return "You sit down and rest."


@command(
    name="sleep",
    category=CommandCategory.MOVEMENT,
    help_text="Sleep for maximum regeneration. You are vulnerable while sleeping.",
    usage="sleep",
    min_position=Position.SLEEPING,
)
async def cmd_sleep(player_id: EntityId, args: List[str]) -> str:
    """Go to sleep for maximum regeneration."""

    # Check if in combat
    combat_actor = get_component_actor("Combat")
    combat_data = await combat_actor.get.remote(player_id)

    if combat_data and combat_data.is_in_combat:
        return "You can't sleep while fighting!"

    position_actor = get_component_actor("Position")
    position_data = await position_actor.get.remote(player_id)

    if not position_data:
        from game.components.position import PositionData

        position_data = PositionData()

    if position_data.position == Position.SLEEPING:
        return "You are already sleeping."

    if position_data.position == Position.DEAD:
        return "You can't do that while dead."

    def do_sleep(p):
        p.sleep()

    await position_actor.mutate.remote(player_id, do_sleep)

    return "You lie down and go to sleep."


@command(
    name="awake",
    aliases=["aw"],
    category=CommandCategory.MOVEMENT,
    help_text="Wake up from sleeping.",
    usage="awake",
    min_position=Position.SLEEPING,
)
async def cmd_awake(player_id: EntityId, args: List[str]) -> str:
    """Wake up from sleep."""

    position_actor = get_component_actor("Position")
    position_data = await position_actor.get.remote(player_id)

    if not position_data:
        return "You are not sleeping."

    if position_data.position != Position.SLEEPING:
        return "You are not sleeping."

    def do_wake(p):
        p.wake()

    await position_actor.mutate.remote(player_id, do_wake)

    return "You wake up and stop sleeping."
