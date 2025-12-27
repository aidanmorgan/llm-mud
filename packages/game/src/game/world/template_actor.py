"""
Distributed Template Registry Actor

A Ray actor that provides distributed storage for all templates.
This replaces the process-local TemplateRegistry singleton, enabling
multiple Python processes to share templates via the Ray cluster.
"""

import ray
from ray.actor import ActorHandle
from typing import Dict, List, Optional, Any
import logging

from .templates import (
    RoomTemplate,
    MobTemplate,
    ItemTemplate,
    PortalTemplate,
)

logger = logging.getLogger(__name__)

ACTOR_NAME = "template_registry"
ACTOR_NAMESPACE = "llmmud"


@ray.remote
class TemplateRegistryActor:
    """
    Distributed registry for all templates.

    This actor is the single source of truth for templates across
    all processes connected to the Ray cluster. Templates can be
    looked up by template_id or vnum.
    """

    def __init__(self):
        self._rooms: Dict[str, RoomTemplate] = {}
        self._mobs: Dict[str, MobTemplate] = {}
        self._items: Dict[str, ItemTemplate] = {}
        self._portals: Dict[str, PortalTemplate] = {}

        # Vnum lookups
        self._room_vnums: Dict[int, str] = {}
        self._mob_vnums: Dict[int, str] = {}
        self._item_vnums: Dict[int, str] = {}

        # Version for cache invalidation
        self._version: int = 0

        logger.info("TemplateRegistryActor initialized")

    def _increment_version(self) -> None:
        """Increment version after any mutation."""
        self._version += 1

    # =========================================================================
    # Version / Cache Support
    # =========================================================================

    def get_version(self) -> int:
        """Get current registry version for cache invalidation."""
        return self._version

    def get_stats(self) -> Dict[str, Any]:
        """Get registry statistics."""
        return {
            "rooms": len(self._rooms),
            "mobs": len(self._mobs),
            "items": len(self._items),
            "portals": len(self._portals),
            "version": self._version,
        }

    # =========================================================================
    # Room Templates
    # =========================================================================

    def register_room(self, template: RoomTemplate) -> None:
        """Register a single room template."""
        self._rooms[template.template_id] = template
        if template.vnum > 0:
            self._room_vnums[template.vnum] = template.template_id
        self._increment_version()
        logger.debug(f"Registered room template: {template.template_id}")

    def register_rooms_batch(self, templates: List[RoomTemplate]) -> int:
        """Register multiple room templates at once. Returns count."""
        for template in templates:
            self._rooms[template.template_id] = template
            if template.vnum > 0:
                self._room_vnums[template.vnum] = template.template_id
        self._increment_version()
        logger.info(f"Registered {len(templates)} room templates (batch)")
        return len(templates)

    def get_room(self, template_id: str) -> Optional[RoomTemplate]:
        """Get room template by ID."""
        return self._rooms.get(template_id)

    def get_room_by_vnum(self, vnum: int) -> Optional[RoomTemplate]:
        """Get room template by vnum."""
        template_id = self._room_vnums.get(vnum)
        if template_id:
            return self._rooms.get(template_id)
        return None

    def get_all_rooms(self) -> Dict[str, RoomTemplate]:
        """Get all room templates."""
        return self._rooms.copy()

    def get_rooms_in_zone(self, zone_id: str) -> List[RoomTemplate]:
        """Get all rooms in a zone."""
        return [r for r in self._rooms.values() if r.zone_id == zone_id]

    def unregister_room(self, template_id: str) -> bool:
        """Remove a room template. Returns True if found."""
        if template_id in self._rooms:
            template = self._rooms.pop(template_id)
            if template.vnum > 0 and template.vnum in self._room_vnums:
                del self._room_vnums[template.vnum]
            self._increment_version()
            return True
        return False

    # =========================================================================
    # Mob Templates
    # =========================================================================

    def register_mob(self, template: MobTemplate) -> None:
        """Register a single mob template."""
        self._mobs[template.template_id] = template
        if template.vnum > 0:
            self._mob_vnums[template.vnum] = template.template_id
        self._increment_version()
        logger.debug(f"Registered mob template: {template.template_id}")

    def register_mobs_batch(self, templates: List[MobTemplate]) -> int:
        """Register multiple mob templates at once. Returns count."""
        for template in templates:
            self._mobs[template.template_id] = template
            if template.vnum > 0:
                self._mob_vnums[template.vnum] = template.template_id
        self._increment_version()
        logger.info(f"Registered {len(templates)} mob templates (batch)")
        return len(templates)

    def get_mob(self, template_id: str) -> Optional[MobTemplate]:
        """Get mob template by ID."""
        return self._mobs.get(template_id)

    def get_mob_by_vnum(self, vnum: int) -> Optional[MobTemplate]:
        """Get mob template by vnum."""
        template_id = self._mob_vnums.get(vnum)
        if template_id:
            return self._mobs.get(template_id)
        return None

    def get_all_mobs(self) -> Dict[str, MobTemplate]:
        """Get all mob templates."""
        return self._mobs.copy()

    def get_mobs_in_zone(self, zone_id: str) -> List[MobTemplate]:
        """Get all mobs in a zone."""
        return [m for m in self._mobs.values() if m.zone_id == zone_id]

    def unregister_mob(self, template_id: str) -> bool:
        """Remove a mob template. Returns True if found."""
        if template_id in self._mobs:
            template = self._mobs.pop(template_id)
            if template.vnum > 0 and template.vnum in self._mob_vnums:
                del self._mob_vnums[template.vnum]
            self._increment_version()
            return True
        return False

    # =========================================================================
    # Item Templates
    # =========================================================================

    def register_item(self, template: ItemTemplate) -> None:
        """Register a single item template."""
        self._items[template.template_id] = template
        if template.vnum > 0:
            self._item_vnums[template.vnum] = template.template_id
        self._increment_version()
        logger.debug(f"Registered item template: {template.template_id}")

    def register_items_batch(self, templates: List[ItemTemplate]) -> int:
        """Register multiple item templates at once. Returns count."""
        for template in templates:
            self._items[template.template_id] = template
            if template.vnum > 0:
                self._item_vnums[template.vnum] = template.template_id
        self._increment_version()
        logger.info(f"Registered {len(templates)} item templates (batch)")
        return len(templates)

    def get_item(self, template_id: str) -> Optional[ItemTemplate]:
        """Get item template by ID."""
        return self._items.get(template_id)

    def get_item_by_vnum(self, vnum: int) -> Optional[ItemTemplate]:
        """Get item template by vnum."""
        template_id = self._item_vnums.get(vnum)
        if template_id:
            return self._items.get(template_id)
        return None

    def get_all_items(self) -> Dict[str, ItemTemplate]:
        """Get all item templates."""
        return self._items.copy()

    def get_items_in_zone(self, zone_id: str) -> List[ItemTemplate]:
        """Get all items in a zone."""
        return [i for i in self._items.values() if i.zone_id == zone_id]

    def unregister_item(self, template_id: str) -> bool:
        """Remove an item template. Returns True if found."""
        if template_id in self._items:
            template = self._items.pop(template_id)
            if template.vnum > 0 and template.vnum in self._item_vnums:
                del self._item_vnums[template.vnum]
            self._increment_version()
            return True
        return False

    # =========================================================================
    # Portal Templates
    # =========================================================================

    def register_portal(self, template: PortalTemplate) -> None:
        """Register a single portal template."""
        self._portals[template.template_id] = template
        self._increment_version()
        logger.debug(f"Registered portal template: {template.template_id}")

    def register_portals_batch(self, templates: List[PortalTemplate]) -> int:
        """Register multiple portal templates at once. Returns count."""
        for template in templates:
            self._portals[template.template_id] = template
        self._increment_version()
        logger.info(f"Registered {len(templates)} portal templates (batch)")
        return len(templates)

    def get_portal(self, template_id: str) -> Optional[PortalTemplate]:
        """Get portal template by ID."""
        return self._portals.get(template_id)

    def get_all_portals(self) -> Dict[str, PortalTemplate]:
        """Get all portal templates."""
        return self._portals.copy()

    def get_portals_in_zone(self, zone_id: str) -> List[PortalTemplate]:
        """Get all portals in a zone."""
        return [p for p in self._portals.values() if p.zone_id == zone_id]

    def unregister_portal(self, template_id: str) -> bool:
        """Remove a portal template. Returns True if found."""
        if template_id in self._portals:
            del self._portals[template_id]
            self._increment_version()
            return True
        return False

    # =========================================================================
    # Bulk Operations
    # =========================================================================

    def clear_zone(self, zone_id: str) -> Dict[str, int]:
        """Remove all templates from a zone. Returns counts of removed items."""
        counts = {"rooms": 0, "mobs": 0, "items": 0, "portals": 0}

        # Rooms
        room_ids = [r.template_id for r in self._rooms.values() if r.zone_id == zone_id]
        for template_id in room_ids:
            if self.unregister_room(template_id):
                counts["rooms"] += 1

        # Mobs
        mob_ids = [m.template_id for m in self._mobs.values() if m.zone_id == zone_id]
        for template_id in mob_ids:
            if self.unregister_mob(template_id):
                counts["mobs"] += 1

        # Items
        item_ids = [i.template_id for i in self._items.values() if i.zone_id == zone_id]
        for template_id in item_ids:
            if self.unregister_item(template_id):
                counts["items"] += 1

        # Portals
        portal_ids = [p.template_id for p in self._portals.values() if p.zone_id == zone_id]
        for template_id in portal_ids:
            if self.unregister_portal(template_id):
                counts["portals"] += 1

        logger.info(f"Cleared zone {zone_id}: {counts}")
        return counts

    def clear_all(self) -> None:
        """Remove all templates."""
        self._rooms.clear()
        self._mobs.clear()
        self._items.clear()
        self._portals.clear()
        self._room_vnums.clear()
        self._mob_vnums.clear()
        self._item_vnums.clear()
        self._increment_version()
        logger.info("Cleared all templates")


# =============================================================================
# Actor Lifecycle Functions
# =============================================================================


def start_template_registry() -> ActorHandle:
    """
    Start the template registry actor.

    Should be called once during server initialization.
    Returns the actor handle.
    """
    actor: ActorHandle = TemplateRegistryActor.options(
        name=ACTOR_NAME,
        namespace=ACTOR_NAMESPACE,
        lifetime="detached",
    ).remote()  # type: ignore[assignment]
    logger.info(f"Started TemplateRegistryActor as {ACTOR_NAMESPACE}/{ACTOR_NAME}")
    return actor


def get_template_registry_actor() -> ActorHandle:
    """
    Get the template registry actor.

    Returns the existing actor handle from the Ray cluster.
    Raises ValueError if the actor doesn't exist.
    """
    try:
        return ray.get_actor(ACTOR_NAME, namespace=ACTOR_NAMESPACE)
    except ValueError:
        raise ValueError(
            "TemplateRegistryActor not found. " "Ensure start_template_registry() was called first."
        )


def template_registry_exists() -> bool:
    """Check if the template registry actor exists."""
    try:
        ray.get_actor(ACTOR_NAME, namespace=ACTOR_NAMESPACE)
        return True
    except ValueError:
        return False


def stop_template_registry() -> bool:
    """
    Stop and kill the template registry actor.

    Returns True if successfully killed, False if actor wasn't found.
    """
    try:
        actor = ray.get_actor(ACTOR_NAME, namespace=ACTOR_NAMESPACE)
        ray.kill(actor)
        logger.info(f"Stopped TemplateRegistryActor {ACTOR_NAMESPACE}/{ACTOR_NAME}")
        return True
    except ValueError:
        logger.warning("TemplateRegistryActor not found, nothing to stop")
        return False
    except Exception as e:
        logger.error(f"Error stopping TemplateRegistryActor: {e}")
        return False
