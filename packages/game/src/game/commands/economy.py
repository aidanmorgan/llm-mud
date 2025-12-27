"""
Economy Commands

Commands for shopping, banking, and player trading.
"""

from typing import List, Optional
from datetime import datetime, timedelta

from core import EntityId
from core.component import get_component_actor
from .registry import command, CommandCategory
from ..components.position import Position
from ..components.economy import TradeState


# =============================================================================
# Helper Functions
# =============================================================================


async def _find_merchant_in_room(room_id: EntityId) -> Optional[EntityId]:
    """Find a merchant NPC in the room."""
    location_actor = get_component_actor("Location")
    dialogue_actor = get_component_actor("Dialogue")
    shop_actor = get_component_actor("Shop")

    all_locations = await location_actor.get_all.remote()

    for entity_id, location in all_locations.items():
        if location.room_id != room_id:
            continue

        # Check if this is a merchant
        dialogue = await dialogue_actor.get.remote(entity_id)
        if dialogue and dialogue.is_merchant:
            # Verify they have a shop
            shop = await shop_actor.get.remote(entity_id)
            if shop:
                return entity_id

    return None


async def _find_banker_in_room(room_id: EntityId) -> Optional[EntityId]:
    """Find a banker NPC in the room."""
    location_actor = get_component_actor("Location")
    dialogue_actor = get_component_actor("Dialogue")

    all_locations = await location_actor.get_all.remote()

    for entity_id, location in all_locations.items():
        if location.room_id != room_id:
            continue

        dialogue = await dialogue_actor.get.remote(entity_id)
        if dialogue and dialogue.is_banker:
            return entity_id

    return None


async def _find_player_in_room(
    room_id: EntityId,
    keyword: str,
    exclude_id: EntityId,
) -> Optional[EntityId]:
    """Find a player in the room by keyword."""
    location_actor = get_component_actor("Location")
    identity_actor = get_component_actor("Identity")
    player_actor = get_component_actor("Player")

    all_locations = await location_actor.get_all.remote()

    for entity_id, location in all_locations.items():
        if location.room_id != room_id:
            continue
        if entity_id == exclude_id:
            continue

        player = await player_actor.get.remote(entity_id)
        if not player:
            continue

        identity = await identity_actor.get.remote(entity_id)
        if identity:
            if keyword.lower() in identity.name.lower():
                return entity_id
            for kw in identity.keywords:
                if keyword.lower() in kw.lower():
                    return entity_id

    return None


async def _find_item_in_inventory(
    player_id: EntityId,
    keyword: str,
    ordinal: int = 1,
) -> Optional[EntityId]:
    """Find an item in player's inventory."""
    container_actor = get_component_actor("Container")
    identity_actor = get_component_actor("Identity")

    container = await container_actor.get.remote(player_id)
    if not container or not container.contents:
        return None

    matches = 0
    for item_id in container.contents:
        identity = await identity_actor.get.remote(item_id)
        if not identity:
            continue

        if keyword.lower() in identity.name.lower():
            matches += 1
            if matches == ordinal:
                return item_id

        for kw in identity.keywords:
            if keyword.lower() in kw.lower():
                matches += 1
                if matches == ordinal:
                    return item_id
                break

    return None


def _parse_ordinal(keyword: str) -> tuple:
    """Parse ordinal prefix from keyword."""
    if "." in keyword:
        parts = keyword.split(".", 1)
        if parts[0].isdigit():
            return (int(parts[0]), parts[1])
    return (1, keyword)


async def _send_to_player(player_id: EntityId, message: str) -> None:
    """Send a message to a player."""
    try:
        import ray
        from network.protocol import create_text

        gateway = ray.get_actor("gateway", namespace="llmmud")
        await gateway.send_to_player.remote(player_id, create_text(message))
    except Exception:
        pass


# =============================================================================
# Shop Commands
# =============================================================================


@command(
    name="list",
    aliases=["browse", "goods"],
    category=CommandCategory.OBJECT,
    help_text="List items for sale at a shop.",
    usage="list [vendor]",
    min_position=Position.RESTING,
)
async def cmd_list(player_id: EntityId, args: List[str]) -> str:
    """List items available at a shop."""
    location_actor = get_component_actor("Location")
    player_location = await location_actor.get.remote(player_id)

    if not player_location or not player_location.room_id:
        return "You are nowhere."

    merchant_id = await _find_merchant_in_room(player_location.room_id)

    if not merchant_id:
        return "There is no merchant here."

    shop_actor = get_component_actor("Shop")
    identity_actor = get_component_actor("Identity")

    shop = await shop_actor.get.remote(merchant_id)
    if not shop:
        return "This merchant has nothing to sell."

    merchant_identity = await identity_actor.get.remote(merchant_id)
    merchant_name = merchant_identity.name if merchant_identity else "The merchant"

    if not shop.inventory:
        return f"{merchant_name} has nothing for sale."

    # Get item templates to show names and prices
    try:
        import ray
        template_registry = ray.get_actor("template_registry", namespace="llmmud")
    except Exception:
        return "Shop system unavailable."

    lines = [f"{shop.shop_name}", "=" * len(shop.shop_name), ""]
    lines.append(f"{'Item':<30} {'Price':>10} {'Stock':>8}")
    lines.append("-" * 50)

    for template_id, shop_item in shop.inventory.items():
        if not shop_item.is_in_stock():
            continue

        template = await template_registry.get_item.remote(template_id)
        if not template:
            continue

        # Calculate price
        base_value = shop_item.base_price if shop_item.base_price else template.value
        price = shop.get_buy_price(base_value)

        # Stock display
        if shop_item.is_unlimited():
            stock_str = "  --"
        else:
            stock_str = f"{shop_item.stock:>4}"

        lines.append(f"{template.name:<30} {price:>10}g {stock_str:>8}")

    lines.append("")
    lines.append(f"Use 'buy <item>' to purchase.")
    lines.append(f"Use 'sell <item>' to sell your items.")

    return "\n".join(lines)


@command(
    name="buy",
    aliases=["purchase"],
    category=CommandCategory.OBJECT,
    help_text="Buy an item from a shop.",
    usage="buy <item>",
    min_position=Position.RESTING,
)
async def cmd_buy(player_id: EntityId, args: List[str]) -> str:
    """Buy an item from a merchant."""
    if not args:
        return "Buy what?"

    location_actor = get_component_actor("Location")
    player_location = await location_actor.get.remote(player_id)

    if not player_location or not player_location.room_id:
        return "You are nowhere."

    merchant_id = await _find_merchant_in_room(player_location.room_id)
    if not merchant_id:
        return "There is no merchant here."

    shop_actor = get_component_actor("Shop")
    shop = await shop_actor.get.remote(merchant_id)
    if not shop:
        return "This merchant has nothing to sell."

    # Parse item keyword
    keyword = " ".join(args).lower()

    # Find matching item in shop inventory
    try:
        import ray
        template_registry = ray.get_actor("template_registry", namespace="llmmud")
    except Exception:
        return "Shop system unavailable."

    matching_template_id = None
    matching_template = None

    for template_id, shop_item in shop.inventory.items():
        if not shop_item.is_in_stock():
            continue

        template = await template_registry.get_item.remote(template_id)
        if not template:
            continue

        if keyword in template.name.lower() or keyword in template_id.lower():
            matching_template_id = template_id
            matching_template = template
            break

        # Check keywords
        for kw in template.keywords:
            if keyword in kw.lower():
                matching_template_id = template_id
                matching_template = template
                break

        if matching_template_id:
            break

    if not matching_template_id:
        return f"The merchant doesn't sell '{keyword}'."

    shop_item = shop.inventory[matching_template_id]

    # Calculate price
    base_value = shop_item.base_price if shop_item.base_price else matching_template.value
    price = shop.get_buy_price(base_value)

    # Check player's gold
    stats_actor = get_component_actor("Stats")
    player_stats = await stats_actor.get.remote(player_id)

    if not player_stats:
        return "You have no money."

    if player_stats.gold < price:
        return f"You can't afford {matching_template.name} ({price} gold). You have {player_stats.gold} gold."

    # Check player's inventory capacity
    container_actor = get_component_actor("Container")
    player_container = await container_actor.get.remote(player_id)

    if not player_container:
        return "You can't carry anything."

    if not player_container.can_add_item(matching_template.weight):
        if player_container.is_full:
            return "You can't carry any more items."
        return "That's too heavy for you to carry."

    # Create the item
    try:
        entity_factory = ray.get_actor("entity_factory", namespace="llmmud")
        item_id = await entity_factory.spawn_item.remote(matching_template_id)
    except Exception as e:
        return f"Failed to create item: {e}"

    if not item_id:
        return "Failed to create item."

    # Deduct gold
    def deduct_gold(stats):
        stats.gold -= price

    await stats_actor.mutate.remote(player_id, deduct_gold)

    # Reduce shop stock
    def reduce_stock(s):
        if matching_template_id in s.inventory:
            s.inventory[matching_template_id].reduce_stock()

    await shop_actor.mutate.remote(merchant_id, reduce_stock)

    # Add item to inventory
    def add_to_inventory(container):
        container.add_item(item_id, matching_template.weight)

    await container_actor.mutate.remote(player_id, add_to_inventory)

    return f"You buy {matching_template.name} for {price} gold."


@command(
    name="sell",
    category=CommandCategory.OBJECT,
    help_text="Sell an item to a shop.",
    usage="sell <item>",
    min_position=Position.RESTING,
)
async def cmd_sell(player_id: EntityId, args: List[str]) -> str:
    """Sell an item to a merchant."""
    if not args:
        return "Sell what?"

    location_actor = get_component_actor("Location")
    player_location = await location_actor.get.remote(player_id)

    if not player_location or not player_location.room_id:
        return "You are nowhere."

    merchant_id = await _find_merchant_in_room(player_location.room_id)
    if not merchant_id:
        return "There is no merchant here."

    shop_actor = get_component_actor("Shop")
    shop = await shop_actor.get.remote(merchant_id)
    if not shop:
        return "This merchant isn't buying."

    # Find item in inventory
    ordinal, keyword = _parse_ordinal(args[0])
    item_id = await _find_item_in_inventory(player_id, keyword, ordinal)

    if not item_id:
        return f"You don't have '{keyword}'."

    # Get item details
    item_actor = get_component_actor("Item")
    identity_actor = get_component_actor("Identity")

    item_data = await item_actor.get.remote(item_id)
    if not item_data:
        return "You can't sell that."

    # Check if bound or quest item
    if item_data.is_bound:
        return "You can't sell that item - it's bound to you."
    if item_data.is_quest_item:
        return "You can't sell quest items."

    # Check if merchant accepts this item type
    if shop.accepted_item_types:
        if item_data.item_type.value not in shop.accepted_item_types:
            return "The merchant isn't interested in that type of item."

    # Calculate sell price
    sell_price = shop.get_sell_price(item_data.value)

    if sell_price <= 0:
        return "The merchant won't buy that - it's worthless."

    # Check if shop has enough gold
    if shop.shop_gold < sell_price:
        return "The merchant doesn't have enough gold to buy that."

    # Get item name
    item_identity = await identity_actor.get.remote(item_id)
    item_name = item_identity.name if item_identity else "something"

    # Remove item from inventory
    container_actor = get_component_actor("Container")

    def remove_from_inventory(container):
        container.remove_item(item_id, item_data.weight)

    await container_actor.mutate.remote(player_id, remove_from_inventory)

    # Delete the item entity (it's absorbed by the shop)
    try:
        import ray
        entity_factory = ray.get_actor("entity_factory", namespace="llmmud")
        await entity_factory.destroy.remote(item_id)
    except Exception:
        pass

    # Add gold to player
    stats_actor = get_component_actor("Stats")

    def add_gold(stats):
        stats.gold += sell_price

    await stats_actor.mutate.remote(player_id, add_gold)

    # Deduct from shop gold
    def deduct_shop_gold(s):
        s.shop_gold -= sell_price

    await shop_actor.mutate.remote(merchant_id, deduct_shop_gold)

    return f"You sell {item_name} for {sell_price} gold."


@command(
    name="value",
    aliases=["appraise", "price"],
    category=CommandCategory.OBJECT,
    help_text="Check what a merchant would pay for an item.",
    usage="value <item>",
    min_position=Position.RESTING,
)
async def cmd_value(player_id: EntityId, args: List[str]) -> str:
    """Check the value of an item at a shop."""
    if not args:
        return "Value what?"

    location_actor = get_component_actor("Location")
    player_location = await location_actor.get.remote(player_id)

    if not player_location or not player_location.room_id:
        return "You are nowhere."

    merchant_id = await _find_merchant_in_room(player_location.room_id)
    if not merchant_id:
        return "There is no merchant here to appraise items."

    shop_actor = get_component_actor("Shop")
    shop = await shop_actor.get.remote(merchant_id)
    if not shop:
        return "This merchant can't appraise items."

    # Find item in inventory
    ordinal, keyword = _parse_ordinal(args[0])
    item_id = await _find_item_in_inventory(player_id, keyword, ordinal)

    if not item_id:
        return f"You don't have '{keyword}'."

    # Get item details
    item_actor = get_component_actor("Item")
    identity_actor = get_component_actor("Identity")

    item_data = await item_actor.get.remote(item_id)
    item_identity = await identity_actor.get.remote(item_id)
    item_name = item_identity.name if item_identity else "that"

    if not item_data:
        return f"The merchant isn't interested in {item_name}."

    # Check if sellable
    if item_data.is_bound:
        return f"You can't sell {item_name} - it's bound to you."
    if item_data.is_quest_item:
        return f"You can't sell {item_name} - it's a quest item."

    # Calculate values
    base_value = item_data.value
    sell_price = shop.get_sell_price(base_value)

    lines = [f"=== {item_name} ==="]
    lines.append(f"Base value: {base_value} gold")
    lines.append(f"Merchant offers: {sell_price} gold")
    lines.append(f"({int(shop.sell_markdown * 100)}% of base value)")

    return "\n".join(lines)


# =============================================================================
# Banking Commands
# =============================================================================


@command(
    name="deposit",
    category=CommandCategory.OBJECT,
    help_text="Deposit gold into your bank account.",
    usage="deposit <amount|all>",
    min_position=Position.RESTING,
)
async def cmd_deposit(player_id: EntityId, args: List[str]) -> str:
    """Deposit gold at a bank."""
    if not args:
        return "Deposit how much?"

    location_actor = get_component_actor("Location")
    player_location = await location_actor.get.remote(player_id)

    if not player_location or not player_location.room_id:
        return "You are nowhere."

    banker_id = await _find_banker_in_room(player_location.room_id)
    if not banker_id:
        return "There is no banker here."

    stats_actor = get_component_actor("Stats")
    player_stats = await stats_actor.get.remote(player_id)

    if not player_stats:
        return "You have no gold."

    # Parse amount
    amount_str = args[0].lower()
    if amount_str == "all":
        amount = player_stats.gold
    else:
        try:
            amount = int(amount_str)
        except ValueError:
            return "That's not a valid amount."

    if amount <= 0:
        return "You must deposit at least 1 gold."

    if amount > player_stats.gold:
        return f"You only have {player_stats.gold} gold on hand."

    # Transfer gold
    def do_deposit(stats):
        stats.gold -= amount
        stats.bank_gold += amount

    await stats_actor.mutate.remote(player_id, do_deposit)

    return f"You deposit {amount} gold. Bank balance: {player_stats.bank_gold + amount} gold."


@command(
    name="withdraw",
    category=CommandCategory.OBJECT,
    help_text="Withdraw gold from your bank account.",
    usage="withdraw <amount|all>",
    min_position=Position.RESTING,
)
async def cmd_withdraw(player_id: EntityId, args: List[str]) -> str:
    """Withdraw gold from a bank."""
    if not args:
        return "Withdraw how much?"

    location_actor = get_component_actor("Location")
    player_location = await location_actor.get.remote(player_id)

    if not player_location or not player_location.room_id:
        return "You are nowhere."

    banker_id = await _find_banker_in_room(player_location.room_id)
    if not banker_id:
        return "There is no banker here."

    stats_actor = get_component_actor("Stats")
    player_stats = await stats_actor.get.remote(player_id)

    if not player_stats:
        return "You have no bank account."

    # Parse amount
    amount_str = args[0].lower()
    if amount_str == "all":
        amount = player_stats.bank_gold
    else:
        try:
            amount = int(amount_str)
        except ValueError:
            return "That's not a valid amount."

    if amount <= 0:
        return "You must withdraw at least 1 gold."

    if amount > player_stats.bank_gold:
        return f"You only have {player_stats.bank_gold} gold in the bank."

    # Transfer gold
    def do_withdraw(stats):
        stats.bank_gold -= amount
        stats.gold += amount

    await stats_actor.mutate.remote(player_id, do_withdraw)

    return f"You withdraw {amount} gold. Bank balance: {player_stats.bank_gold - amount} gold."


@command(
    name="balance",
    aliases=["bank"],
    category=CommandCategory.INFO,
    help_text="Check your bank balance.",
    usage="balance",
    min_position=Position.RESTING,
)
async def cmd_balance(player_id: EntityId, args: List[str]) -> str:
    """Check bank balance."""
    location_actor = get_component_actor("Location")
    player_location = await location_actor.get.remote(player_id)

    if not player_location or not player_location.room_id:
        return "You are nowhere."

    banker_id = await _find_banker_in_room(player_location.room_id)
    if not banker_id:
        return "There is no banker here."

    stats_actor = get_component_actor("Stats")
    player_stats = await stats_actor.get.remote(player_id)

    if not player_stats:
        return "You have no bank account."

    lines = ["=== Bank Balance ==="]
    lines.append(f"Gold in bank: {player_stats.bank_gold}")
    lines.append(f"Gold on hand: {player_stats.gold}")
    lines.append(f"Total wealth: {player_stats.gold + player_stats.bank_gold}")

    return "\n".join(lines)


# =============================================================================
# Trading Commands
# =============================================================================


@command(
    name="trade",
    category=CommandCategory.COMMUNICATION,
    help_text="Initiate a trade with another player.",
    usage="trade <player>",
    min_position=Position.STANDING,
)
async def cmd_trade(player_id: EntityId, args: List[str]) -> str:
    """Start a trade with another player."""
    if not args:
        return "Trade with whom?"

    location_actor = get_component_actor("Location")
    player_location = await location_actor.get.remote(player_id)

    if not player_location or not player_location.room_id:
        return "You are nowhere."

    # Find target player
    target_id = await _find_player_in_room(
        player_location.room_id,
        args[0],
        player_id,
    )

    if not target_id:
        return f"You don't see '{args[0]}' here."

    # Check if either player is already in a trade
    trade_actor = get_component_actor("Trade")

    player_trade = await trade_actor.get.remote(player_id)
    if player_trade and player_trade.is_active():
        return "You're already in a trade. Use 'decline' to cancel it."

    target_trade = await trade_actor.get.remote(target_id)
    if target_trade and target_trade.is_active():
        return "They're already in a trade."

    # Get names
    identity_actor = get_component_actor("Identity")
    player_identity = await identity_actor.get.remote(player_id)
    target_identity = await identity_actor.get.remote(target_id)

    player_name = player_identity.name if player_identity else "Someone"
    target_name = target_identity.name if target_identity else "someone"

    # Create trade data
    from ..components.economy import TradeData, TradeOffer

    now = datetime.utcnow()
    trade_data = TradeData(
        initiator_id=player_id,
        target_id=target_id,
        initiator_offer=TradeOffer(),
        target_offer=TradeOffer(),
        state=TradeState.PENDING,
        created_at=now,
        expires_at=now + timedelta(seconds=300),
    )

    # Set trade data on both players
    await trade_actor.set.remote(player_id, trade_data)
    await trade_actor.set.remote(target_id, trade_data)

    # Notify target
    await _send_to_player(
        target_id,
        f"{player_name} wants to trade with you. Type 'accept' to start trading or 'decline' to refuse.",
    )

    return f"You request to trade with {target_name}. Waiting for them to accept..."


@command(
    name="accept",
    category=CommandCategory.COMMUNICATION,
    help_text="Accept a trade request.",
    usage="accept",
    min_position=Position.STANDING,
)
async def cmd_accept(player_id: EntityId, args: List[str]) -> str:
    """Accept a pending trade request."""
    trade_actor = get_component_actor("Trade")
    trade = await trade_actor.get.remote(player_id)

    if not trade:
        return "You don't have any pending trades."

    if not trade.is_active():
        return "That trade has expired."

    if trade.state != TradeState.PENDING:
        if trade.state == TradeState.NEGOTIATING:
            return "The trade is already active."
        return "That trade has ended."

    # Only the target can accept
    if player_id != trade.target_id:
        return "You initiated this trade - wait for them to accept."

    # Accept the trade
    def do_accept(t):
        t.accept()

    await trade_actor.mutate.remote(player_id, do_accept)
    await trade_actor.mutate.remote(trade.initiator_id, do_accept)

    # Get names
    identity_actor = get_component_actor("Identity")
    initiator_identity = await identity_actor.get.remote(trade.initiator_id)
    initiator_name = initiator_identity.name if initiator_identity else "Someone"

    # Notify initiator
    await _send_to_player(
        trade.initiator_id,
        f"Your trade request was accepted! Use 'offer <item>' to add items.",
    )

    return f"You accept {initiator_name}'s trade. Use 'offer <item>' or 'offer <amount> gold' to add to your offer."


@command(
    name="decline",
    aliases=["cancel"],
    category=CommandCategory.COMMUNICATION,
    help_text="Decline or cancel a trade.",
    usage="decline",
    min_position=Position.STANDING,
)
async def cmd_decline(player_id: EntityId, args: List[str]) -> str:
    """Decline or cancel a trade."""
    trade_actor = get_component_actor("Trade")
    trade = await trade_actor.get.remote(player_id)

    if not trade:
        return "You don't have any pending trades."

    if not trade.is_active():
        return "That trade has already ended."

    other_id = trade.get_other_player(player_id)

    # Cancel the trade
    def do_cancel(t):
        t.cancel()

    await trade_actor.mutate.remote(player_id, do_cancel)
    if other_id:
        await trade_actor.mutate.remote(other_id, do_cancel)

    # Get player name
    identity_actor = get_component_actor("Identity")
    player_identity = await identity_actor.get.remote(player_id)
    player_name = player_identity.name if player_identity else "Someone"

    # Notify other player
    if other_id:
        await _send_to_player(other_id, f"{player_name} cancelled the trade.")

    return "Trade cancelled."


@command(
    name="offer",
    category=CommandCategory.COMMUNICATION,
    help_text="Add an item or gold to your trade offer.",
    usage="offer <item> | offer <amount> gold",
    min_position=Position.STANDING,
)
async def cmd_offer(player_id: EntityId, args: List[str]) -> str:
    """Add something to your trade offer."""
    if not args:
        return "Offer what?"

    trade_actor = get_component_actor("Trade")
    trade = await trade_actor.get.remote(player_id)

    if not trade:
        return "You're not in a trade."

    if trade.state != TradeState.NEGOTIATING:
        if trade.state == TradeState.PENDING:
            return "The trade hasn't been accepted yet."
        return "The trade has ended."

    # Check if offering gold
    if len(args) >= 2 and args[1].lower() == "gold":
        try:
            amount = int(args[0])
        except ValueError:
            return "That's not a valid amount."

        if amount < 0:
            return "You can't offer negative gold."

        # Check if player has enough gold
        stats_actor = get_component_actor("Stats")
        player_stats = await stats_actor.get.remote(player_id)

        if player_stats.gold < amount:
            return f"You only have {player_stats.gold} gold."

        # Update offer
        def set_gold(t):
            offer = t.get_offer_for(player_id)
            if offer:
                offer.set_gold(amount)

        await trade_actor.mutate.remote(player_id, set_gold)

        other_id = trade.get_other_player(player_id)
        if other_id:
            await trade_actor.mutate.remote(other_id, set_gold)

            identity_actor = get_component_actor("Identity")
            player_identity = await identity_actor.get.remote(player_id)
            player_name = player_identity.name if player_identity else "Someone"
            await _send_to_player(other_id, f"{player_name} offers {amount} gold.")

        return f"You offer {amount} gold."

    # Offering an item
    ordinal, keyword = _parse_ordinal(args[0])
    item_id = await _find_item_in_inventory(player_id, keyword, ordinal)

    if not item_id:
        return f"You don't have '{keyword}'."

    # Check if item is tradeable
    item_actor = get_component_actor("Item")
    item_data = await item_actor.get.remote(item_id)

    if item_data and item_data.is_bound:
        return "You can't trade that item - it's bound to you."
    if item_data and item_data.is_quest_item:
        return "You can't trade quest items."

    # Get item name
    identity_actor = get_component_actor("Identity")
    item_identity = await identity_actor.get.remote(item_id)
    item_name = item_identity.name if item_identity else "something"

    # Check if already in offer
    my_offer = trade.get_offer_for(player_id)
    if my_offer and item_id in my_offer.items:
        return f"You've already offered {item_name}."

    # Add to offer
    def add_item(t):
        offer = t.get_offer_for(player_id)
        if offer:
            offer.add_item(item_id)

    await trade_actor.mutate.remote(player_id, add_item)

    other_id = trade.get_other_player(player_id)
    if other_id:
        await trade_actor.mutate.remote(other_id, add_item)

        player_identity = await identity_actor.get.remote(player_id)
        player_name = player_identity.name if player_identity else "Someone"
        await _send_to_player(other_id, f"{player_name} offers {item_name}.")

    return f"You offer {item_name}."


@command(
    name="confirm",
    category=CommandCategory.COMMUNICATION,
    help_text="Confirm your trade offer.",
    usage="confirm",
    min_position=Position.STANDING,
)
async def cmd_confirm(player_id: EntityId, args: List[str]) -> str:
    """Confirm your trade offer."""
    trade_actor = get_component_actor("Trade")
    trade = await trade_actor.get.remote(player_id)

    if not trade:
        return "You're not in a trade."

    if trade.state != TradeState.NEGOTIATING:
        if trade.state == TradeState.PENDING:
            return "The trade hasn't been accepted yet."
        return "The trade has ended."

    other_id = trade.get_other_player(player_id)

    # Confirm from this player
    def do_confirm(t):
        t.confirm(player_id)

    await trade_actor.mutate.remote(player_id, do_confirm)
    if other_id:
        await trade_actor.mutate.remote(other_id, do_confirm)

    # Re-fetch to check if both confirmed
    trade = await trade_actor.get.remote(player_id)

    identity_actor = get_component_actor("Identity")
    player_identity = await identity_actor.get.remote(player_id)
    player_name = player_identity.name if player_identity else "Someone"

    if trade.is_both_confirmed():
        # Execute the trade
        return await _execute_trade(player_id, trade)
    else:
        # Notify other player
        if other_id:
            await _send_to_player(
                other_id,
                f"{player_name} has confirmed the trade. Type 'confirm' to complete the trade.",
            )

        return "You confirm your offer. Waiting for the other player to confirm..."


async def _execute_trade(player_id: EntityId, trade) -> str:
    """Execute a confirmed trade."""
    trade_actor = get_component_actor("Trade")
    container_actor = get_component_actor("Container")
    stats_actor = get_component_actor("Stats")
    item_actor = get_component_actor("Item")
    identity_actor = get_component_actor("Identity")

    initiator_id = trade.initiator_id
    target_id = trade.target_id

    initiator_offer = trade.initiator_offer
    target_offer = trade.target_offer

    # Verify items are still valid and in inventory
    for item_id in initiator_offer.items:
        container = await container_actor.get.remote(initiator_id)
        if not container or item_id not in container.contents:
            # Cancel trade
            def do_cancel(t):
                t.cancel()

            await trade_actor.mutate.remote(initiator_id, do_cancel)
            await trade_actor.mutate.remote(target_id, do_cancel)

            await _send_to_player(initiator_id, "Trade cancelled - item no longer available.")
            await _send_to_player(target_id, "Trade cancelled - item no longer available.")
            return "Trade cancelled - an item is no longer available."

    for item_id in target_offer.items:
        container = await container_actor.get.remote(target_id)
        if not container or item_id not in container.contents:
            def do_cancel(t):
                t.cancel()

            await trade_actor.mutate.remote(initiator_id, do_cancel)
            await trade_actor.mutate.remote(target_id, do_cancel)

            await _send_to_player(initiator_id, "Trade cancelled - item no longer available.")
            await _send_to_player(target_id, "Trade cancelled - item no longer available.")
            return "Trade cancelled - an item is no longer available."

    # Verify gold
    initiator_stats = await stats_actor.get.remote(initiator_id)
    target_stats = await stats_actor.get.remote(target_id)

    if initiator_stats.gold < initiator_offer.gold:
        def do_cancel(t):
            t.cancel()

        await trade_actor.mutate.remote(initiator_id, do_cancel)
        await trade_actor.mutate.remote(target_id, do_cancel)
        return "Trade cancelled - not enough gold."

    if target_stats.gold < target_offer.gold:
        def do_cancel(t):
            t.cancel()

        await trade_actor.mutate.remote(initiator_id, do_cancel)
        await trade_actor.mutate.remote(target_id, do_cancel)
        return "Trade cancelled - not enough gold."

    # Execute the trade

    # Transfer items from initiator to target
    for item_id in initiator_offer.items:
        item_data = await item_actor.get.remote(item_id)
        weight = item_data.weight if item_data else 0

        def remove_from_init(c):
            c.remove_item(item_id, weight)

        await container_actor.mutate.remote(initiator_id, remove_from_init)

        def add_to_target(c):
            c.add_item(item_id, weight)

        await container_actor.mutate.remote(target_id, add_to_target)

    # Transfer items from target to initiator
    for item_id in target_offer.items:
        item_data = await item_actor.get.remote(item_id)
        weight = item_data.weight if item_data else 0

        def remove_from_target(c):
            c.remove_item(item_id, weight)

        await container_actor.mutate.remote(target_id, remove_from_target)

        def add_to_init(c):
            c.add_item(item_id, weight)

        await container_actor.mutate.remote(initiator_id, add_to_init)

    # Transfer gold
    gold_diff = initiator_offer.gold - target_offer.gold

    def adjust_initiator_gold(s):
        s.gold -= initiator_offer.gold
        s.gold += target_offer.gold

    def adjust_target_gold(s):
        s.gold -= target_offer.gold
        s.gold += initiator_offer.gold

    await stats_actor.mutate.remote(initiator_id, adjust_initiator_gold)
    await stats_actor.mutate.remote(target_id, adjust_target_gold)

    # Complete the trade
    def do_complete(t):
        t.complete()

    await trade_actor.mutate.remote(initiator_id, do_complete)
    await trade_actor.mutate.remote(target_id, do_complete)

    # Get names for messages
    initiator_identity = await identity_actor.get.remote(initiator_id)
    target_identity = await identity_actor.get.remote(target_id)
    initiator_name = initiator_identity.name if initiator_identity else "Someone"
    target_name = target_identity.name if target_identity else "someone"

    # Notify both players
    other_id = trade.get_other_player(player_id)
    if player_id == initiator_id:
        await _send_to_player(target_id, f"Trade with {initiator_name} completed!")
        return f"Trade with {target_name} completed!"
    else:
        await _send_to_player(initiator_id, f"Trade with {target_name} completed!")
        return f"Trade with {initiator_name} completed!"


@command(
    name="show",
    aliases=["tradeshow"],
    category=CommandCategory.COMMUNICATION,
    help_text="Show the current trade status.",
    usage="show",
    min_position=Position.STANDING,
)
async def cmd_show_trade(player_id: EntityId, args: List[str]) -> str:
    """Show current trade status."""
    trade_actor = get_component_actor("Trade")
    trade = await trade_actor.get.remote(player_id)

    if not trade:
        return "You're not in a trade."

    if not trade.is_active():
        return "That trade has ended."

    identity_actor = get_component_actor("Identity")

    # Get names
    initiator_identity = await identity_actor.get.remote(trade.initiator_id)
    target_identity = await identity_actor.get.remote(trade.target_id)
    initiator_name = initiator_identity.name if initiator_identity else "Initiator"
    target_name = target_identity.name if target_identity else "Target"

    lines = ["=== Trade Status ===", ""]

    # Initiator's offer
    lines.append(f"{initiator_name}'s offer:")
    if trade.initiator_offer.items:
        for item_id in trade.initiator_offer.items:
            item_identity = await identity_actor.get.remote(item_id)
            item_name = item_identity.name if item_identity else "Unknown item"
            lines.append(f"  - {item_name}")
    if trade.initiator_offer.gold > 0:
        lines.append(f"  - {trade.initiator_offer.gold} gold")
    if not trade.initiator_offer.items and trade.initiator_offer.gold == 0:
        lines.append("  (nothing)")
    status = "CONFIRMED" if trade.initiator_offer.confirmed else "not confirmed"
    lines.append(f"  Status: {status}")
    lines.append("")

    # Target's offer
    lines.append(f"{target_name}'s offer:")
    if trade.target_offer.items:
        for item_id in trade.target_offer.items:
            item_identity = await identity_actor.get.remote(item_id)
            item_name = item_identity.name if item_identity else "Unknown item"
            lines.append(f"  - {item_name}")
    if trade.target_offer.gold > 0:
        lines.append(f"  - {trade.target_offer.gold} gold")
    if not trade.target_offer.items and trade.target_offer.gold == 0:
        lines.append("  (nothing)")
    status = "CONFIRMED" if trade.target_offer.confirmed else "not confirmed"
    lines.append(f"  Status: {status}")

    return "\n".join(lines)
