"""World state systems - time, events, day/night cycle."""

from datetime import datetime, timedelta
from typing import Dict, List, Optional
import random

from core.system import System


class WorldTimeSystem(System):
    """
    Updates world time and handles day/night transitions.

    Broadcasts announcements when time of day changes.
    """

    priority = 5  # Run very early

    required_components = ["WorldStateData"]

    _last_announcement: Optional[str] = None

    async def process(self, entity_id: str, components: Dict) -> None:
        """Update world time."""
        from ..components.world import WorldStateData

        world: WorldStateData = components["WorldStateData"]

        # Update time
        announcement = world.update_time()

        # Handle time of day change
        if announcement and announcement != self._last_announcement:
            self._last_announcement = announcement
            # Would broadcast to all players
            world.pending_announcements.append(announcement)

        # Check for expired events
        event_endings = world.remove_expired_events()
        world.pending_announcements.extend(event_endings)


class WorldEventSystem(System):
    """
    Manages world events - scheduling, starting, ending.
    """

    priority = 6

    required_components = ["WorldStateData"]

    # Scheduled events (could be loaded from config)
    _scheduled_events: List[Dict] = []

    async def process(self, entity_id: str, components: Dict) -> None:
        """Check for scheduled events to start."""
        from ..components.world import WorldStateData, WorldEvent, WorldEventType

        world: WorldStateData = components["WorldStateData"]

        # Random event chance (very rare)
        if random.random() < 0.0001:  # ~0.01% per tick
            await self._spawn_random_event(world)

    async def _spawn_random_event(self, world) -> None:
        """Spawn a random world event."""
        from ..components.world import WorldEvent, WorldEventType
        import uuid

        event_templates = [
            {
                "type": WorldEventType.DOUBLE_EXP,
                "name": "Blessing of Knowledge",
                "description": "Experience gains are doubled!",
                "duration_minutes": 60,
                "multipliers": {"exp": 2.0},
            },
            {
                "type": WorldEventType.DOUBLE_GOLD,
                "name": "Fortune's Favor",
                "description": "Gold drops are doubled!",
                "duration_minutes": 60,
                "multipliers": {"gold": 2.0},
            },
            {
                "type": WorldEventType.BLOOD_MOON,
                "name": "Blood Moon Rising",
                "description": "Monsters are stronger but drop better loot!",
                "duration_minutes": 30,
                "multipliers": {"mob_damage": 1.5, "loot_quality": 1.5},
            },
        ]

        template = random.choice(event_templates)
        now = datetime.utcnow()

        event = WorldEvent(
            event_id=str(uuid.uuid4())[:8],
            event_type=template["type"],
            name=template["name"],
            description=template["description"],
            started_at=now,
            ends_at=now + timedelta(minutes=template["duration_minutes"]),
            multipliers=template.get("multipliers", {}),
        )

        world.add_event(event)


class AnnouncementSystem(System):
    """
    Broadcasts pending announcements to all online players.
    """

    priority = 99  # Run last

    required_components = ["WorldStateData"]

    async def process(self, entity_id: str, components: Dict) -> None:
        """Broadcast pending announcements."""
        from ..components.world import WorldStateData

        world: WorldStateData = components["WorldStateData"]

        announcements = world.pop_announcements()
        for announcement in announcements:
            # Would use event system to broadcast
            await self._broadcast_global(announcement)

    async def _broadcast_global(self, message: str) -> None:
        """Broadcast message to all online players."""
        # Would iterate through all connected players
        pass


class ZonePopulationSystem(System):
    """
    Tracks player/mob counts per zone.
    """

    priority = 98

    required_components = ["ZoneStateData"]

    async def update_zone_population(
        self,
        zone_id: str,
        player_delta: int = 0,
        mob_delta: int = 0,
        game_state=None,
    ) -> None:
        """Update zone population counts."""
        from ..components.world import ZoneStateData

        zone_entity_id = f"zone_{zone_id}"
        zone_state = await game_state.get_component(zone_entity_id, "ZoneStateData")

        if not zone_state:
            zone_state = ZoneStateData(zone_id=zone_id)

        zone_state.player_count = max(0, zone_state.player_count + player_delta)
        zone_state.mob_count = max(0, zone_state.mob_count + mob_delta)

        await game_state.set_component(zone_entity_id, "ZoneStateData", zone_state)


async def get_world_state(game_state) -> Optional["WorldStateData"]:
    """Get the global world state."""
    from ..components.world import WorldStateData

    return await game_state.get_component("world", "WorldStateData")


async def initialize_world_state(game_state) -> None:
    """Initialize world state if not exists."""
    from ..components.world import WorldStateData, GameTime

    existing = await game_state.get_component("world", "WorldStateData")
    if not existing:
        world = WorldStateData(
            game_time=GameTime(year=1, month=3, day=15, hour=8, minute=0),
        )
        await game_state.set_component("world", "WorldStateData", world)
