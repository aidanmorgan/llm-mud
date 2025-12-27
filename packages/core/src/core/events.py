"""
Distributed Event System

A Ray-based pub/sub eventing system that enables:
- Events scoped to entities, rooms, regions, zones, or global
- Multiple Python processes subscribing to events via Ray cluster
- Intelligent event distribution using Ray's actor model
- Topic-based filtering (combat, movement, chat, system, etc.)

Architecture:
- EventBus: Central Ray actor coordinating all event distribution
- EventRouter: Per-scope actors for efficient local distribution
- Subscribers: Can be actors, callbacks, or queues
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from typing import (
    Any,
    Callable,
    Dict,
    List,
    Optional,
    Set,
    Tuple,
    TypeVar,
    Union,
    Protocol,
    runtime_checkable,
)
import asyncio
import logging
import ray

from .types import EntityId

logger = logging.getLogger(__name__)


# =============================================================================
# Event Scope and Topic Enums
# =============================================================================


class EventScope(str, Enum):
    """Scope at which an event is published."""

    ENTITY = "entity"  # Single entity (player, mob, item)
    ROOM = "room"  # All entities in a room
    REGION = "region"  # All rooms in a dynamic region
    ZONE = "zone"  # All rooms in a static zone
    WORLD = "world"  # Global broadcast


class EventTopic(str, Enum):
    """Topic categories for event filtering."""

    # Core game events
    COMBAT = "combat"
    MOVEMENT = "movement"
    DEATH = "death"
    SPAWN = "spawn"

    # Communication
    CHAT = "chat"
    EMOTE = "emote"
    CHANNEL = "channel"

    # Items and inventory
    ITEM_PICKUP = "item_pickup"
    ITEM_DROP = "item_drop"
    ITEM_USE = "item_use"
    EQUIPMENT = "equipment"

    # Skills and effects
    SKILL = "skill"
    EFFECT = "effect"
    BUFF = "buff"
    DEBUFF = "debuff"

    # Room and environment
    AMBIENT = "ambient"
    ROOM_CHANGE = "room_change"
    REGION_ENTER = "region_enter"
    REGION_EXIT = "region_exit"

    # System events
    SYSTEM = "system"
    TICK = "tick"
    CONNECTION = "connection"
    ADMIN = "admin"

    # Economy
    TRADE = "trade"
    SHOP = "shop"
    GOLD = "gold"

    # Quests
    QUEST = "quest"
    OBJECTIVE = "objective"

    # Catch-all
    CUSTOM = "custom"


class EventPriority(int, Enum):
    """Priority levels for event processing order."""

    CRITICAL = 0  # System-critical, process immediately
    HIGH = 10  # Combat, death
    NORMAL = 50  # Standard gameplay events
    LOW = 100  # Ambient, cosmetic
    BACKGROUND = 200  # Logging, analytics


# =============================================================================
# Event Data Classes
# =============================================================================


@dataclass(frozen=True)
class EventTarget:
    """Identifies the target scope for an event."""

    scope: EventScope
    target_id: str  # Entity ID, room ID, region ID, zone ID, or "*" for world

    @classmethod
    def entity(cls, entity_id: EntityId) -> "EventTarget":
        return cls(scope=EventScope.ENTITY, target_id=str(entity_id))

    @classmethod
    def room(cls, room_id: str) -> "EventTarget":
        return cls(scope=EventScope.ROOM, target_id=room_id)

    @classmethod
    def region(cls, region_id: str) -> "EventTarget":
        return cls(scope=EventScope.REGION, target_id=region_id)

    @classmethod
    def zone(cls, zone_id: str) -> "EventTarget":
        return cls(scope=EventScope.ZONE, target_id=zone_id)

    @classmethod
    def world(cls) -> "EventTarget":
        return cls(scope=EventScope.WORLD, target_id="*")


@dataclass
class GameEvent:
    """Base class for all game events."""

    event_id: str  # Unique event identifier
    topic: EventTopic
    target: EventTarget
    timestamp: datetime = field(default_factory=datetime.utcnow)
    priority: EventPriority = EventPriority.NORMAL
    source_entity: Optional[EntityId] = None  # Who/what caused this event
    data: Dict[str, Any] = field(default_factory=dict)

    # Propagation control
    propagate_up: bool = True  # Propagate to parent scopes
    consumed: bool = False  # Has this event been consumed

    def consume(self) -> None:
        """Mark event as consumed to stop further propagation."""
        object.__setattr__(self, "consumed", True)


@dataclass
class CombatEvent(GameEvent):
    """Combat-specific event."""

    attacker_id: Optional[EntityId] = None
    defender_id: Optional[EntityId] = None
    damage: int = 0
    damage_type: str = ""
    skill_used: Optional[str] = None
    is_critical: bool = False
    is_kill: bool = False

    def __post_init__(self):
        if not hasattr(self, "topic") or self.topic is None:
            object.__setattr__(self, "topic", EventTopic.COMBAT)


@dataclass
class MovementEvent(GameEvent):
    """Movement-specific event."""

    entity_id: Optional[EntityId] = None
    from_room: Optional[str] = None
    to_room: Optional[str] = None
    direction: Optional[str] = None
    is_teleport: bool = False

    def __post_init__(self):
        if not hasattr(self, "topic") or self.topic is None:
            object.__setattr__(self, "topic", EventTopic.MOVEMENT)


@dataclass
class ChatEvent(GameEvent):
    """Chat/communication event."""

    speaker_id: Optional[EntityId] = None
    speaker_name: str = ""
    message: str = ""
    channel: Optional[str] = None  # For channel messages

    def __post_init__(self):
        if not hasattr(self, "topic") or self.topic is None:
            object.__setattr__(self, "topic", EventTopic.CHAT)


@dataclass
class ItemEvent(GameEvent):
    """Item-related event."""

    item_id: Optional[EntityId] = None
    item_name: str = ""
    actor_id: Optional[EntityId] = None  # Who performed the action
    container_id: Optional[EntityId] = None  # For put/get from container
    quantity: int = 1


@dataclass
class SkillEvent(GameEvent):
    """Skill/ability use event."""

    caster_id: Optional[EntityId] = None
    skill_id: str = ""
    skill_name: str = ""
    target_ids: List[EntityId] = field(default_factory=list)
    mana_cost: int = 0
    effect_applied: Optional[str] = None

    def __post_init__(self):
        if not hasattr(self, "topic") or self.topic is None:
            object.__setattr__(self, "topic", EventTopic.SKILL)


@dataclass
class SystemEvent(GameEvent):
    """System-level event."""

    event_type: str = ""  # shutdown, restart, maintenance, etc.
    message: str = ""

    def __post_init__(self):
        if not hasattr(self, "topic") or self.topic is None:
            object.__setattr__(self, "topic", EventTopic.SYSTEM)


# =============================================================================
# Subscription Types
# =============================================================================


@dataclass
class Subscription:
    """Represents a subscription to events."""

    subscription_id: str
    subscriber_id: str  # Identifier for the subscriber
    scope: EventScope
    target_id: str  # "*" for all within scope
    topics: Set[EventTopic]  # Empty set means all topics
    priority_filter: Optional[EventPriority] = None  # Only events >= this priority
    handler_actor: Optional[str] = None  # Ray actor name to call
    handler_method: str = "handle_event"  # Method to call on actor
    created_at: datetime = field(default_factory=datetime.utcnow)
    expires_at: Optional[datetime] = None


@runtime_checkable
class EventHandler(Protocol):
    """Protocol for event handlers."""

    async def handle_event(self, event: GameEvent) -> None:
        """Handle a game event."""
        ...


# =============================================================================
# Event Router (Per-Scope Actor)
# =============================================================================


@ray.remote
class EventRouter:
    """
    Routes events within a specific scope.

    One EventRouter handles events for a scope type (room, region, zone).
    Uses Ray's actor model for horizontal scaling - multiple routers
    can handle different subsets of the same scope type.
    """

    def __init__(self, scope: EventScope, partition_id: str = "default"):
        self._scope = scope
        self._partition_id = partition_id
        self._subscriptions: Dict[str, List[Subscription]] = {}  # target_id -> subs
        self._wildcard_subs: List[Subscription] = []  # target_id == "*"
        self._pending_events: asyncio.Queue = asyncio.Queue()
        self._running = False
        logger.info(f"EventRouter initialized for {scope.value}:{partition_id}")

    async def subscribe(self, subscription: Subscription) -> bool:
        """Add a subscription."""
        if subscription.target_id == "*":
            self._wildcard_subs.append(subscription)
        else:
            if subscription.target_id not in self._subscriptions:
                self._subscriptions[subscription.target_id] = []
            self._subscriptions[subscription.target_id].append(subscription)
        logger.debug(
            f"Added subscription {subscription.subscription_id} "
            f"for {subscription.target_id}"
        )
        return True

    async def unsubscribe(self, subscription_id: str) -> bool:
        """Remove a subscription."""
        # Check wildcards
        self._wildcard_subs = [
            s for s in self._wildcard_subs if s.subscription_id != subscription_id
        ]
        # Check target-specific
        for target_id in self._subscriptions:
            self._subscriptions[target_id] = [
                s
                for s in self._subscriptions[target_id]
                if s.subscription_id != subscription_id
            ]
        return True

    async def publish(self, event: GameEvent) -> int:
        """
        Publish an event to matching subscribers.

        Returns the number of subscribers notified.
        """
        if event.consumed:
            return 0

        target_id = event.target.target_id
        matching_subs: List[Subscription] = []

        # Get target-specific subscriptions
        if target_id in self._subscriptions:
            matching_subs.extend(self._subscriptions[target_id])

        # Add wildcard subscriptions
        matching_subs.extend(self._wildcard_subs)

        # Filter by topic and priority
        notified = 0
        for sub in matching_subs:
            # Topic filter
            if sub.topics and event.topic not in sub.topics:
                continue

            # Priority filter
            if sub.priority_filter and event.priority.value > sub.priority_filter.value:
                continue

            # Expiration check
            if sub.expires_at and datetime.utcnow() > sub.expires_at:
                continue

            # Deliver to handler
            try:
                if sub.handler_actor:
                    actor = ray.get_actor(sub.handler_actor, namespace="llmmud")
                    method = getattr(actor, sub.handler_method)
                    await method.remote(event)
                    notified += 1
            except Exception as e:
                logger.error(
                    f"Failed to deliver event to {sub.handler_actor}: {e}"
                )

        return notified

    async def get_subscription_count(self) -> int:
        """Get total number of active subscriptions."""
        count = len(self._wildcard_subs)
        for subs in self._subscriptions.values():
            count += len(subs)
        return count


# =============================================================================
# Event Bus (Central Coordinator)
# =============================================================================


@ray.remote
class EventBus:
    """
    Central event bus coordinating all event distribution.

    The EventBus manages:
    - Creating and managing EventRouter actors per scope
    - Event propagation between scopes
    - Subscription management across the cluster
    - Event batching and efficient distribution

    This is a named actor accessible from any process in the Ray cluster.
    """

    def __init__(self):
        self._routers: Dict[Tuple[EventScope, str], ray.actor.ActorHandle] = {}
        self._subscriptions: Dict[str, Subscription] = {}
        self._next_subscription_id = 0
        self._event_count = 0
        self._scope_hierarchy: Dict[str, Dict[str, str]] = {
            # room_id -> region_id, zone_id
        }
        logger.info("EventBus initialized")

    def _get_router(
        self, scope: EventScope, partition_id: str = "default"
    ) -> ray.actor.ActorHandle:
        """Get or create a router for the given scope and partition."""
        key = (scope, partition_id)
        if key not in self._routers:
            router_name = f"event_router_{scope.value}_{partition_id}"
            self._routers[key] = EventRouter.options(
                name=router_name,
                namespace="llmmud",
                lifetime="detached",
            ).remote(scope, partition_id)
            logger.info(f"Created EventRouter: {router_name}")
        return self._routers[key]

    async def subscribe(
        self,
        subscriber_id: str,
        scope: EventScope,
        target_id: str = "*",
        topics: Optional[List[EventTopic]] = None,
        priority_filter: Optional[EventPriority] = None,
        handler_actor: Optional[str] = None,
        handler_method: str = "handle_event",
        ttl_seconds: Optional[int] = None,
    ) -> str:
        """
        Subscribe to events.

        Args:
            subscriber_id: Unique identifier for the subscriber
            scope: Event scope to subscribe to
            target_id: Specific target or "*" for all in scope
            topics: List of topics to filter, None for all
            priority_filter: Minimum priority to receive
            handler_actor: Ray actor name to deliver events to
            handler_method: Method name on actor to call
            ttl_seconds: Subscription expiration time

        Returns:
            subscription_id: Unique ID for this subscription
        """
        self._next_subscription_id += 1
        sub_id = f"sub_{subscriber_id}_{self._next_subscription_id}"

        expires_at = None
        if ttl_seconds:
            from datetime import timedelta

            expires_at = datetime.utcnow() + timedelta(seconds=ttl_seconds)

        subscription = Subscription(
            subscription_id=sub_id,
            subscriber_id=subscriber_id,
            scope=scope,
            target_id=target_id,
            topics=set(topics) if topics else set(),
            priority_filter=priority_filter,
            handler_actor=handler_actor,
            handler_method=handler_method,
            expires_at=expires_at,
        )

        self._subscriptions[sub_id] = subscription

        # Register with appropriate router
        router = self._get_router(scope)
        await router.subscribe.remote(subscription)

        logger.debug(f"Created subscription {sub_id} for {subscriber_id}")
        return sub_id

    async def unsubscribe(self, subscription_id: str) -> bool:
        """Remove a subscription."""
        if subscription_id not in self._subscriptions:
            return False

        sub = self._subscriptions.pop(subscription_id)
        router = self._get_router(sub.scope)
        await router.unsubscribe.remote(subscription_id)

        logger.debug(f"Removed subscription {subscription_id}")
        return True

    async def publish(self, event: GameEvent) -> int:
        """
        Publish an event to all matching subscribers.

        Handles propagation up the scope hierarchy if propagate_up is True.

        Returns:
            Total number of subscribers notified
        """
        self._event_count += 1
        total_notified = 0

        # Publish to the event's direct scope
        router = self._get_router(event.target.scope)
        notified = await router.publish.remote(event)
        total_notified += notified

        # Propagate up the hierarchy if enabled
        if event.propagate_up and not event.consumed:
            parent_targets = await self._get_parent_targets(event.target)
            for parent_target in parent_targets:
                parent_event = GameEvent(
                    event_id=event.event_id,
                    topic=event.topic,
                    target=parent_target,
                    timestamp=event.timestamp,
                    priority=event.priority,
                    source_entity=event.source_entity,
                    data=event.data,
                    propagate_up=False,  # Don't double-propagate
                )
                parent_router = self._get_router(parent_target.scope)
                notified = await parent_router.publish.remote(parent_event)
                total_notified += notified

        return total_notified

    async def publish_batch(self, events: List[GameEvent]) -> int:
        """
        Publish multiple events efficiently.

        Events are grouped by scope for batch delivery.
        """
        total = 0
        for event in events:
            total += await self.publish(event)
        return total

    async def register_hierarchy(
        self,
        room_id: str,
        region_id: Optional[str] = None,
        zone_id: Optional[str] = None,
    ) -> None:
        """
        Register the scope hierarchy for a room.

        This enables automatic event propagation from room -> region -> zone -> world.
        """
        self._scope_hierarchy[room_id] = {
            "region_id": region_id or "",
            "zone_id": zone_id or "",
        }

    async def _get_parent_targets(self, target: EventTarget) -> List[EventTarget]:
        """Get parent scope targets for propagation."""
        parents = []

        if target.scope == EventScope.ENTITY:
            # Entity events don't have parent scope lookup here
            # They're typically room-scoped
            pass

        elif target.scope == EventScope.ROOM:
            room_id = target.target_id
            if room_id in self._scope_hierarchy:
                hierarchy = self._scope_hierarchy[room_id]
                if hierarchy.get("region_id"):
                    parents.append(EventTarget.region(hierarchy["region_id"]))
                if hierarchy.get("zone_id"):
                    parents.append(EventTarget.zone(hierarchy["zone_id"]))
            parents.append(EventTarget.world())

        elif target.scope == EventScope.REGION:
            # Region -> World
            parents.append(EventTarget.world())

        elif target.scope == EventScope.ZONE:
            # Zone -> World
            parents.append(EventTarget.world())

        return parents

    async def get_stats(self) -> Dict[str, Any]:
        """Get event bus statistics."""
        router_stats = {}
        for (scope, partition), router in self._routers.items():
            count = await router.get_subscription_count.remote()
            router_stats[f"{scope.value}:{partition}"] = count

        return {
            "total_events_published": self._event_count,
            "active_subscriptions": len(self._subscriptions),
            "routers": router_stats,
            "hierarchy_entries": len(self._scope_hierarchy),
        }


# =============================================================================
# Helper Functions
# =============================================================================


_event_bus: Optional[ray.actor.ActorHandle] = None


def get_event_bus() -> ray.actor.ActorHandle:
    """Get the global EventBus actor handle."""
    global _event_bus
    if _event_bus is None:
        try:
            _event_bus = ray.get_actor("event_bus", namespace="llmmud")
        except ValueError:
            # Actor doesn't exist, create it
            _event_bus = EventBus.options(
                name="event_bus",
                namespace="llmmud",
                lifetime="detached",
            ).remote()
            logger.info("Created EventBus actor")
    return _event_bus


async def publish_event(event: GameEvent) -> int:
    """Convenience function to publish an event."""
    bus = get_event_bus()
    return await bus.publish.remote(event)


async def subscribe(
    subscriber_id: str,
    scope: EventScope,
    target_id: str = "*",
    topics: Optional[List[EventTopic]] = None,
    handler_actor: Optional[str] = None,
    handler_method: str = "handle_event",
) -> str:
    """Convenience function to subscribe to events."""
    bus = get_event_bus()
    return await bus.subscribe.remote(
        subscriber_id=subscriber_id,
        scope=scope,
        target_id=target_id,
        topics=topics,
        handler_actor=handler_actor,
        handler_method=handler_method,
    )


def generate_event_id() -> str:
    """Generate a unique event ID."""
    import uuid

    return str(uuid.uuid4())


# =============================================================================
# Event Factory Functions
# =============================================================================


def create_combat_event(
    room_id: str,
    attacker_id: EntityId,
    defender_id: EntityId,
    damage: int,
    damage_type: str = "physical",
    is_critical: bool = False,
    is_kill: bool = False,
    skill_used: Optional[str] = None,
) -> CombatEvent:
    """Factory for combat events."""
    return CombatEvent(
        event_id=generate_event_id(),
        topic=EventTopic.COMBAT,
        target=EventTarget.room(room_id),
        priority=EventPriority.HIGH if is_kill else EventPriority.NORMAL,
        source_entity=attacker_id,
        attacker_id=attacker_id,
        defender_id=defender_id,
        damage=damage,
        damage_type=damage_type,
        is_critical=is_critical,
        is_kill=is_kill,
        skill_used=skill_used,
    )


def create_movement_event(
    entity_id: EntityId,
    from_room: str,
    to_room: str,
    direction: Optional[str] = None,
    is_teleport: bool = False,
) -> MovementEvent:
    """Factory for movement events."""
    return MovementEvent(
        event_id=generate_event_id(),
        topic=EventTopic.MOVEMENT,
        target=EventTarget.room(from_room),  # Notify the room being left
        priority=EventPriority.NORMAL,
        source_entity=entity_id,
        entity_id=entity_id,
        from_room=from_room,
        to_room=to_room,
        direction=direction,
        is_teleport=is_teleport,
    )


def create_chat_event(
    room_id: str,
    speaker_id: EntityId,
    speaker_name: str,
    message: str,
    is_emote: bool = False,
) -> ChatEvent:
    """Factory for chat events."""
    return ChatEvent(
        event_id=generate_event_id(),
        topic=EventTopic.EMOTE if is_emote else EventTopic.CHAT,
        target=EventTarget.room(room_id),
        priority=EventPriority.NORMAL,
        source_entity=speaker_id,
        speaker_id=speaker_id,
        speaker_name=speaker_name,
        message=message,
    )


def create_channel_event(
    channel_name: str,
    speaker_id: EntityId,
    speaker_name: str,
    message: str,
) -> ChatEvent:
    """Factory for channel message events."""
    return ChatEvent(
        event_id=generate_event_id(),
        topic=EventTopic.CHANNEL,
        target=EventTarget.world(),  # Channels are world-scoped
        priority=EventPriority.NORMAL,
        source_entity=speaker_id,
        speaker_id=speaker_id,
        speaker_name=speaker_name,
        message=message,
        channel=channel_name,
    )


def create_system_event(
    event_type: str,
    message: str,
    scope: EventScope = EventScope.WORLD,
    target_id: str = "*",
) -> SystemEvent:
    """Factory for system events."""
    return SystemEvent(
        event_id=generate_event_id(),
        topic=EventTopic.SYSTEM,
        target=EventTarget(scope=scope, target_id=target_id),
        priority=EventPriority.CRITICAL,
        event_type=event_type,
        message=message,
    )
