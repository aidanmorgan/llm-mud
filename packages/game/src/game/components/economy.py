"""
Economy Components

Define shop inventory, trading, and currency systems.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional
from datetime import datetime
from enum import Enum

from core import EntityId, ComponentData


class TradeState(str, Enum):
    """States of a trade session."""

    PENDING = "pending"  # Waiting for other party to accept
    NEGOTIATING = "negotiating"  # Both parties adjusting offers
    CONFIRMED = "confirmed"  # One party confirmed, waiting for other
    COMPLETED = "completed"  # Trade completed successfully
    CANCELLED = "cancelled"  # Trade was cancelled


@dataclass
class ShopItem:
    """
    An item available in a shop's inventory.
    """

    # Item template ID (for restocking)
    template_id: str

    # Current stock
    stock: int = -1  # -1 means unlimited

    # Maximum stock for restocking
    max_stock: int = -1  # -1 means unlimited

    # Custom price override (None = use item's base value)
    base_price: Optional[int] = None

    def is_in_stock(self) -> bool:
        """Check if item is available."""
        return self.stock != 0

    def is_unlimited(self) -> bool:
        """Check if stock is unlimited."""
        return self.stock == -1

    def reduce_stock(self, amount: int = 1) -> bool:
        """Reduce stock, return True if successful."""
        if self.stock == -1:
            return True  # Unlimited
        if self.stock >= amount:
            self.stock -= amount
            return True
        return False

    def add_stock(self, amount: int = 1) -> None:
        """Add stock (for restocking)."""
        if self.stock == -1:
            return  # Unlimited, no need to add
        self.stock += amount
        if self.max_stock > 0:
            self.stock = min(self.stock, self.max_stock)


@dataclass
class ShopData(ComponentData):
    """
    Shop inventory and pricing for merchant NPCs.
    """

    # Shop inventory: template_id -> ShopItem
    inventory: Dict[str, ShopItem] = field(default_factory=dict)

    # Pricing multipliers
    buy_markup: float = 1.5  # Price player pays (150% of base)
    sell_markdown: float = 0.5  # Price player receives (50% of base)

    # Shop properties
    shop_name: str = "Shop"
    shop_keeper_greeting: str = "Welcome! Browse my wares."

    # Restocking
    restock_interval_s: int = 3600  # 1 hour
    last_restock: Optional[datetime] = None
    auto_restock: bool = True

    # Restrictions
    min_level_to_shop: int = 0
    accepted_item_types: List[str] = field(default_factory=list)  # Empty = all

    # Currency
    shop_gold: int = 10000  # Gold available for buying from players

    def get_buy_price(self, base_value: int) -> int:
        """Get price player pays to buy an item."""
        return max(1, int(base_value * self.buy_markup))

    def get_sell_price(self, base_value: int) -> int:
        """Get price player receives for selling an item."""
        return max(0, int(base_value * self.sell_markdown))

    def add_item(self, template_id: str, stock: int = -1, max_stock: int = -1,
                 base_price: Optional[int] = None) -> None:
        """Add an item to shop inventory."""
        self.inventory[template_id] = ShopItem(
            template_id=template_id,
            stock=stock,
            max_stock=max_stock,
            base_price=base_price,
        )

    def remove_item(self, template_id: str) -> bool:
        """Remove an item from shop inventory."""
        if template_id in self.inventory:
            del self.inventory[template_id]
            return True
        return False

    def get_item(self, template_id: str) -> Optional[ShopItem]:
        """Get a shop item by template ID."""
        return self.inventory.get(template_id)

    def needs_restock(self) -> bool:
        """Check if shop needs restocking."""
        if not self.auto_restock:
            return False
        if self.last_restock is None:
            return True
        elapsed = (datetime.utcnow() - self.last_restock).total_seconds()
        return elapsed >= self.restock_interval_s

    def restock(self) -> int:
        """Restock all items to max, return number of items restocked."""
        restocked = 0
        for item in self.inventory.values():
            if item.stock != -1 and item.max_stock > 0:
                if item.stock < item.max_stock:
                    item.stock = item.max_stock
                    restocked += 1
        self.last_restock = datetime.utcnow()
        return restocked


@dataclass
class TradeOffer:
    """
    One party's offer in a trade.
    """

    # Items being offered (entity IDs)
    items: List[EntityId] = field(default_factory=list)

    # Gold being offered
    gold: int = 0

    # Whether this party has confirmed
    confirmed: bool = False

    def add_item(self, item_id: EntityId) -> bool:
        """Add an item to the offer."""
        if item_id in self.items:
            return False
        self.items.append(item_id)
        self.confirmed = False  # Reset confirmation on change
        return True

    def remove_item(self, item_id: EntityId) -> bool:
        """Remove an item from the offer."""
        if item_id not in self.items:
            return False
        self.items.remove(item_id)
        self.confirmed = False
        return True

    def set_gold(self, amount: int) -> bool:
        """Set gold amount."""
        if amount < 0:
            return False
        self.gold = amount
        self.confirmed = False
        return True

    def confirm(self) -> None:
        """Confirm the offer."""
        self.confirmed = True

    def unconfirm(self) -> None:
        """Unconfirm the offer."""
        self.confirmed = False

    def clear(self) -> None:
        """Clear the offer."""
        self.items.clear()
        self.gold = 0
        self.confirmed = False


@dataclass
class TradeData(ComponentData):
    """
    Active trade session between two players.
    """

    # Trade participants
    initiator_id: Optional[EntityId] = None
    target_id: Optional[EntityId] = None

    # Offers from each party
    initiator_offer: TradeOffer = field(default_factory=TradeOffer)
    target_offer: TradeOffer = field(default_factory=TradeOffer)

    # Trade state
    state: TradeState = TradeState.PENDING

    # Trade session info
    created_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None

    # Timeout for trade (seconds)
    timeout_s: int = 300  # 5 minutes

    def is_active(self) -> bool:
        """Check if trade is still active."""
        if self.state in (TradeState.COMPLETED, TradeState.CANCELLED):
            return False
        if self.expires_at and datetime.utcnow() > self.expires_at:
            return False
        return True

    def is_both_confirmed(self) -> bool:
        """Check if both parties have confirmed."""
        return self.initiator_offer.confirmed and self.target_offer.confirmed

    def get_offer_for(self, player_id: EntityId) -> Optional[TradeOffer]:
        """Get the offer for a specific player."""
        if player_id == self.initiator_id:
            return self.initiator_offer
        if player_id == self.target_id:
            return self.target_offer
        return None

    def get_other_offer_for(self, player_id: EntityId) -> Optional[TradeOffer]:
        """Get the other player's offer."""
        if player_id == self.initiator_id:
            return self.target_offer
        if player_id == self.target_id:
            return self.initiator_offer
        return None

    def get_other_player(self, player_id: EntityId) -> Optional[EntityId]:
        """Get the other player's ID."""
        if player_id == self.initiator_id:
            return self.target_id
        if player_id == self.target_id:
            return self.initiator_id
        return None

    def is_participant(self, player_id: EntityId) -> bool:
        """Check if player is part of this trade."""
        return player_id in (self.initiator_id, self.target_id)

    def accept(self) -> None:
        """Accept the trade (target only, moves from PENDING to NEGOTIATING)."""
        if self.state == TradeState.PENDING:
            self.state = TradeState.NEGOTIATING

    def confirm(self, player_id: EntityId) -> bool:
        """Confirm the trade from one party."""
        offer = self.get_offer_for(player_id)
        if offer:
            offer.confirm()
            if self.is_both_confirmed():
                self.state = TradeState.CONFIRMED
            return True
        return False

    def unconfirm(self, player_id: EntityId) -> bool:
        """Unconfirm when offer changes."""
        offer = self.get_offer_for(player_id)
        if offer:
            offer.unconfirm()
            if self.state == TradeState.CONFIRMED:
                self.state = TradeState.NEGOTIATING
            return True
        return False

    def complete(self) -> None:
        """Mark trade as completed."""
        self.state = TradeState.COMPLETED

    def cancel(self) -> None:
        """Cancel the trade."""
        self.state = TradeState.CANCELLED

    def reset(self) -> None:
        """Reset trade data."""
        self.initiator_id = None
        self.target_id = None
        self.initiator_offer = TradeOffer()
        self.target_offer = TradeOffer()
        self.state = TradeState.PENDING
        self.created_at = None
        self.expires_at = None


@dataclass
class BankAccountData(ComponentData):
    """
    Extended banking functionality (beyond basic bank_gold in PlayerStatsData).
    Used for bank NPCs to track available services.
    """

    # Bank properties
    bank_name: str = "Bank"
    bank_greeting: str = "Welcome to the bank. How may I help you?"

    # Transaction fees (percentage)
    deposit_fee_percent: float = 0.0  # Usually free
    withdrawal_fee_percent: float = 0.0  # Usually free

    # Minimum transaction
    min_transaction: int = 1

    # Interest (for future feature)
    interest_rate_daily: float = 0.0

    def get_deposit_fee(self, amount: int) -> int:
        """Calculate deposit fee."""
        return int(amount * self.deposit_fee_percent / 100)

    def get_withdrawal_fee(self, amount: int) -> int:
        """Calculate withdrawal fee."""
        return int(amount * self.withdrawal_fee_percent / 100)
