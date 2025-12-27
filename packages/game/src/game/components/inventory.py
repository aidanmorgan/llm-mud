"""
Inventory Components

Define items, containers, and equipment systems.

Enums:
- EquipmentSlot: Where items can be worn
- ItemType: Categories of items
- ItemRarity: Rarity tiers
- WeaponType: Types of weapons
- ArmorType: Types of armor
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional
from enum import Enum, auto

from core import EntityId, ComponentData
from .combat import DamageType


class EquipmentSlot(str, Enum):
    """Equipment slots for wearing items."""

    HEAD = "head"
    NECK = "neck"
    SHOULDERS = "shoulders"
    CHEST = "chest"
    BACK = "back"
    WAIST = "waist"
    LEGS = "legs"
    FEET = "feet"
    HANDS = "hands"
    FINGER_1 = "finger_1"
    FINGER_2 = "finger_2"
    WRIST_1 = "wrist_1"
    WRIST_2 = "wrist_2"
    MAIN_HAND = "main_hand"
    OFF_HAND = "off_hand"


class ItemType(str, Enum):
    """Categories of items."""

    WEAPON = "weapon"
    ARMOR = "armor"
    CONSUMABLE = "consumable"
    QUEST = "quest"
    MATERIAL = "material"
    CURRENCY = "currency"
    CONTAINER = "container"
    KEY = "key"
    LIGHT = "light"
    MISC = "misc"


class ItemRarity(str, Enum):
    """Item rarity tiers."""

    COMMON = "common"
    UNCOMMON = "uncommon"
    RARE = "rare"
    EPIC = "epic"
    LEGENDARY = "legendary"


class WeaponType(str, Enum):
    """Types of weapons."""

    # Bladed
    SWORD = "sword"
    DAGGER = "dagger"
    AXE = "axe"
    SCIMITAR = "scimitar"

    # Blunt
    MACE = "mace"
    HAMMER = "hammer"
    CLUB = "club"
    FLAIL = "flail"

    # Polearms
    SPEAR = "spear"
    HALBERD = "halberd"
    LANCE = "lance"

    # Ranged
    BOW = "bow"
    CROSSBOW = "crossbow"
    SLING = "sling"

    # Magic
    STAFF = "staff"
    WAND = "wand"

    # Unarmed
    FIST = "fist"

    # Exotic
    WHIP = "whip"
    EXOTIC = "exotic"


class ArmorType(str, Enum):
    """Types of armor weight classes."""

    CLOTH = "cloth"
    LIGHT = "light"
    MEDIUM = "medium"
    HEAVY = "heavy"
    SHIELD = "shield"


class ConsumableEffectType(str, Enum):
    """Types of effects consumables can have."""

    HEAL = "heal"
    RESTORE_MANA = "restore_mana"
    RESTORE_STAMINA = "restore_stamina"
    BUFF = "buff"
    DAMAGE = "damage"
    CURE_POISON = "cure_poison"
    CURE_DISEASE = "cure_disease"
    ANTIDOTE = "antidote"
    FOOD = "food"
    DRINK = "drink"


@dataclass
class ContainerData(ComponentData):
    """
    Allows an entity to hold items (inventory, bags, chests).
    """

    # Items contained: list of item entity IDs
    contents: List[EntityId] = field(default_factory=list)

    # Capacity limits
    max_items: int = 20
    max_weight: float = 100.0
    current_weight: float = 0.0

    # Container properties
    is_closed: bool = False
    is_locked: bool = False
    key_id: Optional[str] = None  # Template ID of key

    @property
    def item_count(self) -> int:
        """Number of items in container."""
        return len(self.contents)

    @property
    def is_full(self) -> bool:
        """Check if container is full."""
        return len(self.contents) >= self.max_items

    @property
    def is_empty(self) -> bool:
        """Check if container is empty."""
        return len(self.contents) == 0

    def can_add_item(self, weight: float = 0.0) -> bool:
        """Check if an item can be added."""
        if self.is_full:
            return False
        if self.current_weight + weight > self.max_weight:
            return False
        return True

    def add_item(self, item_id: EntityId, weight: float = 0.0) -> bool:
        """Add item to container."""
        if not self.can_add_item(weight):
            return False
        self.contents.append(item_id)
        self.current_weight += weight
        return True

    def remove_item(self, item_id: EntityId, weight: float = 0.0) -> bool:
        """Remove item from container."""
        if item_id in self.contents:
            self.contents.remove(item_id)
            self.current_weight = max(0, self.current_weight - weight)
            return True
        return False


@dataclass
class EquipmentSlotsData(ComponentData):
    """
    Equipment slots for wearable items.
    """

    # Slot -> equipped item EntityId
    slots: Dict[str, Optional[EntityId]] = field(
        default_factory=lambda: {slot.value: None for slot in EquipmentSlot}
    )

    def get_equipped(self, slot: EquipmentSlot) -> Optional[EntityId]:
        """Get item equipped in slot."""
        return self.slots.get(slot.value)

    def equip(self, slot: EquipmentSlot, item_id: EntityId) -> Optional[EntityId]:
        """
        Equip item in slot, return previously equipped item if any.
        """
        previous = self.slots.get(slot.value)
        self.slots[slot.value] = item_id
        return previous

    def unequip(self, slot: EquipmentSlot) -> Optional[EntityId]:
        """
        Unequip item from slot, return the item.
        """
        item = self.slots.get(slot.value)
        self.slots[slot.value] = None
        return item

    def get_all_equipped(self) -> List[EntityId]:
        """Get all equipped items."""
        return [item for item in self.slots.values() if item is not None]

    def find_item_slot(self, item_id: EntityId) -> Optional[EquipmentSlot]:
        """Find which slot an item is equipped in."""
        for slot_name, equipped_id in self.slots.items():
            if equipped_id == item_id:
                return EquipmentSlot(slot_name)
        return None


@dataclass
class ItemData(ComponentData):
    """
    Base item properties.
    """

    # Basic properties
    item_type: ItemType = ItemType.MISC
    rarity: ItemRarity = ItemRarity.COMMON

    # Physical properties
    weight: float = 1.0
    value: int = 0  # Base gold value

    # Stacking
    stackable: bool = False
    stack_size: int = 1
    max_stack: int = 1

    # Level requirement
    level_requirement: int = 0

    # Condition/durability
    max_durability: int = 100
    current_durability: int = 100

    # Flags
    is_cursed: bool = False
    is_bound: bool = False  # Can't be traded/dropped
    is_quest_item: bool = False

    @property
    def is_broken(self) -> bool:
        """Check if item is broken."""
        return self.current_durability <= 0

    def damage(self, amount: int = 1) -> None:
        """Reduce durability."""
        self.current_durability = max(0, self.current_durability - amount)

    def repair(self, amount: Optional[int] = None) -> None:
        """Repair durability."""
        if amount is None:
            self.current_durability = self.max_durability
        else:
            self.current_durability = min(self.max_durability, self.current_durability + amount)


@dataclass
class WeaponData(ComponentData):
    """
    Weapon-specific properties.
    """

    # Damage
    damage_dice: str = "1d6"  # Dice notation
    damage_type: DamageType = DamageType.SLASHING

    # Weapon type
    weapon_type: WeaponType = WeaponType.SWORD

    # Properties
    attack_speed: float = 1.0  # Multiplier
    range: int = 0  # 0 = melee
    two_handed: bool = False

    # Bonuses
    hit_bonus: int = 0
    damage_bonus: int = 0

    # Special properties
    special_effects: List[str] = field(default_factory=list)  # e.g., ["fire_damage", "lifesteal"]


@dataclass
class ArmorData(ComponentData):
    """
    Armor-specific properties.
    """

    # Defense
    armor_bonus: int = 0

    # Type affects class restrictions
    armor_type: ArmorType = ArmorType.LIGHT

    # Slot this armor goes in
    slot: EquipmentSlot = EquipmentSlot.CHEST

    # Resistances: maps DamageType to resistance percentage
    resistances: Dict[DamageType, int] = field(default_factory=dict)

    # Penalties
    speed_penalty: int = 0  # Movement speed reduction percentage
    spell_failure: int = 0  # Percentage chance spells fail


@dataclass
class ConsumableData(ComponentData):
    """
    Consumable item effects.
    """

    # Effect type
    effect_type: ConsumableEffectType = ConsumableEffectType.HEAL

    # Effect values
    effect_value: int = 0
    effect_duration_s: Optional[int] = None  # For buffs

    # Usage
    uses_remaining: int = 1
    max_uses: int = 1

    # Cooldown
    cooldown_s: float = 0.0

    @property
    def is_depleted(self) -> bool:
        """Check if consumable is used up."""
        return self.uses_remaining <= 0

    def use(self) -> bool:
        """Use the consumable, return True if successful."""
        if self.uses_remaining > 0:
            self.uses_remaining -= 1
            return True
        return False
