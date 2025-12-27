"""
Player Persistence System

Handles saving and loading player data to/from disk.
Supports both periodic auto-save and on-demand saving.
"""

import asyncio
import json
import logging
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List

import ray
from ray.actor import ActorHandle

from core import EntityId
from core.component import get_component_actor

logger = logging.getLogger(__name__)

# Default save directory
DEFAULT_SAVE_DIR = Path("players")


@dataclass
class PlayerSaveData:
    """All data needed to save/restore a player."""

    player_id: str
    name: str
    created_at: str
    last_login: str

    # Stats
    level: int = 1
    experience: int = 0
    class_name: str = "adventurer"
    race: str = "human"

    # Current stats
    current_hp: int = 100
    max_hp: int = 100
    current_mana: int = 50
    max_mana: int = 50
    current_stamina: int = 100
    max_stamina: int = 100

    # Attributes
    strength: int = 10
    dexterity: int = 10
    constitution: int = 10
    intelligence: int = 10
    wisdom: int = 10
    charisma: int = 10

    # Location
    room_id: str = "limbo:1"

    # Inventory (list of item template IDs)
    inventory: List[str] = None

    # Equipment (slot -> item template ID)
    equipment: Dict[str, str] = None

    # Preferences
    preferences: Dict[str, Any] = None

    # Channels subscribed to
    channels: List[str] = None

    # Play time in seconds
    total_playtime: int = 0

    def __post_init__(self):
        if self.inventory is None:
            self.inventory = []
        if self.equipment is None:
            self.equipment = {}
        if self.preferences is None:
            self.preferences = {}
        if self.channels is None:
            self.channels = ["ooc", "newbie"]


class PlayerSaveError(Exception):
    """Error during player save/load."""

    pass


async def save_player(player_id: EntityId, save_dir: Path = DEFAULT_SAVE_DIR) -> bool:
    """
    Save a player's data to disk.

    Collects all relevant component data and writes to a JSON file.
    """
    try:
        save_data = await _collect_player_data(player_id)
        if not save_data:
            logger.warning(f"No data to save for player {player_id}")
            return False

        # Ensure save directory exists
        save_dir.mkdir(parents=True, exist_ok=True)

        # Save to file
        save_path = save_dir / f"{save_data.player_id}.json"
        with open(save_path, "w") as f:
            json.dump(asdict(save_data), f, indent=2, default=str)

        logger.info(f"Saved player {save_data.name} to {save_path}")
        return True

    except Exception as e:
        logger.error(f"Failed to save player {player_id}: {e}")
        return False


async def load_player(player_id: str, save_dir: Path = DEFAULT_SAVE_DIR) -> Optional[PlayerSaveData]:
    """
    Load a player's data from disk.

    Returns None if no save file exists.
    """
    save_path = save_dir / f"{player_id}.json"

    if not save_path.exists():
        return None

    try:
        with open(save_path, "r") as f:
            data = json.load(f)

        return PlayerSaveData(**data)

    except Exception as e:
        logger.error(f"Failed to load player {player_id}: {e}")
        return None


async def restore_player(player_id: EntityId, save_data: PlayerSaveData) -> bool:
    """
    Restore a player's data from save data.

    Updates all relevant components with saved values.
    """
    try:
        identity_actor = get_component_actor("Identity")
        stats_actor = get_component_actor("Stats")
        location_actor = get_component_actor("Location")

        # Update identity
        def update_identity(identity):
            identity.name = save_data.name

        await identity_actor.mutate.remote(player_id, update_identity)

        # Update stats
        def update_stats(stats):
            stats.level = save_data.level
            stats.experience = save_data.experience
            stats.class_name = save_data.class_name
            stats.race = save_data.race
            stats.current_hp = save_data.current_hp
            stats.max_hp = save_data.max_hp
            stats.current_mana = save_data.current_mana
            stats.max_mana = save_data.max_mana
            stats.current_stamina = save_data.current_stamina
            stats.max_stamina = save_data.max_stamina
            # Attributes
            if hasattr(stats, "attributes"):
                stats.attributes.strength = save_data.strength
                stats.attributes.dexterity = save_data.dexterity
                stats.attributes.constitution = save_data.constitution
                stats.attributes.intelligence = save_data.intelligence
                stats.attributes.wisdom = save_data.wisdom
                stats.attributes.charisma = save_data.charisma

        await stats_actor.mutate.remote(player_id, update_stats)

        # Update location
        room_id = EntityId("room", save_data.room_id)

        def update_location(loc):
            loc.room_id = room_id
            loc.entered_at = datetime.utcnow()

        await location_actor.mutate.remote(player_id, update_location)

        logger.info(f"Restored player {save_data.name}")
        return True

    except Exception as e:
        logger.error(f"Failed to restore player {player_id}: {e}")
        return False


async def _collect_player_data(player_id: EntityId) -> Optional[PlayerSaveData]:
    """Collect all player data from components."""
    try:
        identity_actor = get_component_actor("Identity")
        stats_actor = get_component_actor("Stats")
        location_actor = get_component_actor("Location")

        identity = await identity_actor.get.remote(player_id)
        stats = await stats_actor.get.remote(player_id)
        location = await location_actor.get.remote(player_id)

        if not identity:
            return None

        save_data = PlayerSaveData(
            player_id=str(player_id),
            name=identity.name,
            created_at=datetime.utcnow().isoformat(),
            last_login=datetime.utcnow().isoformat(),
        )

        if stats:
            save_data.level = getattr(stats, "level", 1)
            save_data.experience = getattr(stats, "experience", 0)
            save_data.class_name = getattr(stats, "class_name", "adventurer")
            save_data.race = getattr(stats, "race", "human")
            save_data.current_hp = getattr(stats, "current_hp", 100)
            save_data.max_hp = getattr(stats, "max_hp", 100)
            save_data.current_mana = getattr(stats, "current_mana", 50)
            save_data.max_mana = getattr(stats, "max_mana", 50)
            save_data.current_stamina = getattr(stats, "current_stamina", 100)
            save_data.max_stamina = getattr(stats, "max_stamina", 100)

            if hasattr(stats, "attributes"):
                save_data.strength = getattr(stats.attributes, "strength", 10)
                save_data.dexterity = getattr(stats.attributes, "dexterity", 10)
                save_data.constitution = getattr(stats.attributes, "constitution", 10)
                save_data.intelligence = getattr(stats.attributes, "intelligence", 10)
                save_data.wisdom = getattr(stats.attributes, "wisdom", 10)
                save_data.charisma = getattr(stats.attributes, "charisma", 10)

        if location and location.room_id:
            save_data.room_id = str(location.room_id)

        return save_data

    except Exception as e:
        logger.error(f"Error collecting player data: {e}")
        return None


def player_save_exists(player_id: str, save_dir: Path = DEFAULT_SAVE_DIR) -> bool:
    """Check if a player save file exists."""
    save_path = save_dir / f"{player_id}.json"
    return save_path.exists()


def list_saved_players(save_dir: Path = DEFAULT_SAVE_DIR) -> List[str]:
    """List all saved player IDs."""
    if not save_dir.exists():
        return []
    return [f.stem for f in save_dir.glob("*.json")]


# =============================================================================
# Auto-Save System
# =============================================================================


@ray.remote
class AutoSaveManager:
    """
    Ray actor that periodically saves all online players.

    Features:
    - Configurable auto-save interval
    - Staggered saves to avoid I/O spikes
    - Manual save triggering
    """

    def __init__(self, save_interval_s: float = 300.0, save_dir: str = "players"):
        self._save_interval = save_interval_s
        self._save_dir = Path(save_dir)
        self._running = False
        self._save_task: Optional[asyncio.Task] = None
        self._last_save: Dict[str, datetime] = {}

        logger.info(
            f"AutoSaveManager initialized (interval: {save_interval_s}s, dir: {save_dir})"
        )

    async def start(self) -> None:
        """Start the auto-save loop."""
        if self._running:
            return

        self._running = True
        self._save_task = asyncio.create_task(self._auto_save_loop())
        logger.info("Auto-save started")

    async def stop(self) -> None:
        """Stop the auto-save loop."""
        self._running = False
        if self._save_task:
            self._save_task.cancel()
            try:
                await self._save_task
            except asyncio.CancelledError:
                pass
        logger.info("Auto-save stopped")

    async def _auto_save_loop(self) -> None:
        """Background loop that saves all players periodically."""
        while self._running:
            try:
                await asyncio.sleep(self._save_interval)
                await self.save_all_players()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in auto-save loop: {e}")

    async def save_all_players(self) -> int:
        """Save all online players. Returns number of players saved."""
        try:
            connection_actor = get_component_actor("Connection")
            all_connections = await connection_actor.get_all.remote()

            saved = 0
            for entity_id, connection in all_connections.items():
                if not connection.is_connected:
                    continue

                if await save_player(entity_id, self._save_dir):
                    self._last_save[str(entity_id)] = datetime.utcnow()
                    saved += 1

                # Small delay between saves to avoid I/O spikes
                await asyncio.sleep(0.1)

            logger.info(f"Auto-save complete: {saved} players saved")
            return saved

        except Exception as e:
            logger.error(f"Error in save_all_players: {e}")
            return 0

    async def save_player(self, player_id: EntityId) -> bool:
        """Save a single player immediately."""
        result = await save_player(player_id, self._save_dir)
        if result:
            self._last_save[str(player_id)] = datetime.utcnow()
        return result

    async def get_last_save(self, player_id: EntityId) -> Optional[str]:
        """Get the last save time for a player."""
        last = self._last_save.get(str(player_id))
        return last.isoformat() if last else None

    async def get_stats(self) -> Dict[str, Any]:
        """Get auto-save statistics."""
        return {
            "running": self._running,
            "interval_seconds": self._save_interval,
            "save_directory": str(self._save_dir),
            "players_tracked": len(self._last_save),
        }


# =============================================================================
# Actor Lifecycle
# =============================================================================

ACTOR_NAME = "autosave_manager"
ACTOR_NAMESPACE = "llmmud"

_autosave_actor: Optional[ActorHandle] = None


def start_autosave_manager(
    save_interval_s: float = 300.0, save_dir: str = "players"
) -> ActorHandle:
    """Start the auto-save manager actor."""
    global _autosave_actor

    actor: ActorHandle = AutoSaveManager.options(
        name=ACTOR_NAME,
        namespace=ACTOR_NAMESPACE,
        lifetime="detached",
    ).remote(save_interval_s, save_dir)

    _autosave_actor = actor
    logger.info("Started AutoSaveManager")
    return actor


def get_autosave_manager() -> ActorHandle:
    """Get the auto-save manager actor."""
    global _autosave_actor
    if _autosave_actor is None:
        _autosave_actor = ray.get_actor(ACTOR_NAME, namespace=ACTOR_NAMESPACE)
    return _autosave_actor


def autosave_manager_exists() -> bool:
    """Check if the auto-save manager exists."""
    try:
        ray.get_actor(ACTOR_NAME, namespace=ACTOR_NAMESPACE)
        return True
    except ValueError:
        return False


def stop_autosave_manager() -> bool:
    """Stop the auto-save manager."""
    try:
        actor = ray.get_actor(ACTOR_NAME, namespace=ACTOR_NAMESPACE)
        ray.kill(actor)
        logger.info("Stopped AutoSaveManager")
        return True
    except ValueError:
        return False
