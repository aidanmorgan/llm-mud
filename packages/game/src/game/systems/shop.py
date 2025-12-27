"""
Shop System

Handles shop restocking and economy-related periodic tasks.
"""

import logging
from typing import Dict, List, Any

import ray
from ray.actor import ActorHandle

from core import EntityId, ComponentData, System

logger = logging.getLogger(__name__)


@ray.remote
class ShopRestockSystem(System):
    """
    Handles periodic restocking of shop inventories.

    Required components:
    - Shop: Has inventory, restock configuration

    Shops automatically restock based on their configured interval.
    """

    def __init__(self):
        super().__init__(
            system_type="ShopRestockSystem",
            required_components=["Shop"],
            optional_components=["Identity"],
            dependencies=[],
            priority=70,  # Low priority, runs after gameplay systems
        )
        self._restock_events: List[Dict[str, Any]] = []

    async def process_entities(
        self,
        entities: Dict[EntityId, Dict[str, ComponentData]],
        write_buffer: ActorHandle,
    ) -> int:
        """
        Check and restock shops that need it.
        """
        processed = 0
        self._restock_events.clear()

        for entity_id, components in entities.items():
            shop = components["Shop"]
            identity = components.get("Identity")

            # Skip if doesn't need restocking
            if not shop.needs_restock():
                continue

            # Restock the shop
            shop_name = identity.name if identity else str(entity_id)

            def do_restock(s):
                return s.restock()

            restocked_count = await write_buffer.mutate.remote("Shop", entity_id, do_restock)

            if restocked_count > 0:
                self._restock_events.append({
                    "entity": entity_id,
                    "shop_name": shop_name,
                    "items_restocked": restocked_count,
                })
                logger.debug(f"Restocked {restocked_count} items at {shop_name}")

            processed += 1

        return processed

    async def get_pending_events(self) -> List[Dict[str, Any]]:
        """Get restock events from last tick."""
        return self._restock_events.copy()


@ray.remote
class TradeCleanupSystem(System):
    """
    Cleans up expired trade sessions.

    Required components:
    - Trade: Has trade session data

    Cancels trades that have exceeded their timeout.
    """

    def __init__(self):
        super().__init__(
            system_type="TradeCleanupSystem",
            required_components=["Trade"],
            optional_components=["Identity"],
            dependencies=[],
            priority=75,  # Very low priority
        )
        self._cleanup_events: List[Dict[str, Any]] = []

    async def process_entities(
        self,
        entities: Dict[EntityId, Dict[str, ComponentData]],
        write_buffer: ActorHandle,
    ) -> int:
        """
        Check and cancel expired trades.
        """
        from datetime import datetime

        processed = 0
        self._cleanup_events.clear()

        for entity_id, components in entities.items():
            trade = components["Trade"]

            # Skip if no active trade or already ended
            if not trade.is_active():
                continue

            # Check if expired
            if trade.expires_at and datetime.utcnow() > trade.expires_at:
                # Cancel the trade
                def do_cancel(t):
                    t.cancel()

                await write_buffer.mutate.remote("Trade", entity_id, do_cancel)

                # Also cancel for the other party
                other_id = trade.get_other_player(entity_id)
                if other_id:
                    await write_buffer.mutate.remote("Trade", other_id, do_cancel)

                self._cleanup_events.append({
                    "entity": entity_id,
                    "other_entity": other_id,
                    "reason": "timeout",
                })

                # Notify players
                await self._notify_trade_expired(entity_id, other_id)

                processed += 1

        return processed

    async def _notify_trade_expired(
        self, player1_id: EntityId, player2_id: EntityId
    ) -> None:
        """Notify both players that their trade expired."""
        try:
            from network.protocol import create_text

            gateway = ray.get_actor("gateway", namespace="llmmud")

            message = "Your trade has expired."
            await gateway.send_to_player.remote(player1_id, create_text(message))
            if player2_id:
                await gateway.send_to_player.remote(player2_id, create_text(message))
        except Exception:
            pass

    async def get_pending_events(self) -> List[Dict[str, Any]]:
        """Get cleanup events from last tick."""
        return self._cleanup_events.copy()
