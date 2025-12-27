"""
Entity Factory

Creates entities from templates by registering their components
with the ECS system.

Supports both:
- Local TemplateRegistry (legacy, for single-process)
- Distributed TemplateRegistryActor (for multi-process deployments)
"""

import uuid
import logging
from typing import Optional
from dataclasses import fields

from ray.actor import ActorHandle

from core import (
    EntityId,
    ComponentData,
    core_component_engine,
    core_entity_index,
)

from .templates import (
    TemplateRegistry,
    get_template_registry,
)
from .template_actor import (
    get_template_registry_actor,
)

from ..components import (
    # Identity
    StaticIdentityData,
    # Spatial
    LocationData,
    StaticRoomData,
    MobStatsData,
    PlayerStatsData,
    AttributeBlock,
    # Combat
    CombatData,
    DamageType,
    ContainerData,
    EquipmentSlotsData,
    ItemData,
    WeaponData,
    ArmorData,
    ConsumableData,
    ItemType,
    ItemRarity,
    EquipmentSlot,
    WeaponType,
    ArmorType,
    # AI
    StaticAIData,
    DialogueData,
    BehaviorType,
    CombatStyle,
    # Player
    PlayerConnectionData,
    PlayerProgressData,
    QuestLogData,
    # Portal
    PortalData,
    InstanceType,
)

logger = logging.getLogger(__name__)


class EntityFactory:
    """
    Creates entities from templates.

    Entities are created by:
    1. Generating a unique EntityId
    2. Creating component data from template
    3. Registering components with Component actors
    4. Updating EntityIndex
    """

    def __init__(
        self,
        registry: Optional[TemplateRegistry] = None,
        component_engine: Optional[ActorHandle] = None,
        entity_index: Optional[ActorHandle] = None,
    ):
        self.registry = registry or get_template_registry()
        self._component_engine = component_engine
        self._entity_index = entity_index

    def _get_component_engine(self) -> ActorHandle:
        """Get component engine lazily."""
        if self._component_engine is None:
            self._component_engine = core_component_engine()
        return self._component_engine

    def _get_entity_index(self) -> ActorHandle:
        """Get entity index lazily."""
        if self._entity_index is None:
            self._entity_index = core_entity_index()
        return self._entity_index

    def _generate_id(self) -> str:
        """Generate a unique entity instance ID."""
        return uuid.uuid4().hex[:12]

    async def _register_component(
        self, entity: EntityId, component_type: str, data: ComponentData
    ) -> None:
        """Register a component for an entity."""
        from core.component import get_component_actor

        try:
            actor = get_component_actor(component_type)
            # Use the create method with a callback to set data
            await actor.create.remote(entity, lambda c: self._copy_data(c, data))

            # Update entity index
            index = self._get_entity_index()
            await index.register.remote(entity, component_type)

        except Exception as e:
            logger.error(f"Error registering component {component_type} for {entity}: {e}")
            raise

    def _copy_data(self, target: ComponentData, source: ComponentData) -> None:
        """Copy data from source to target component."""
        for f in fields(source):
            if f.name != "owner":
                setattr(target, f.name, getattr(source, f.name))

    # =========================================================================
    # Room Creation
    # =========================================================================

    async def create_room(
        self, template_id: str, instance_id: Optional[str] = None
    ) -> Optional[EntityId]:
        """
        Create a room entity from template.
        """
        template = self.registry.get_room(template_id)
        if not template:
            logger.error(f"Room template not found: {template_id}")
            return None

        entity_id = EntityId(id=instance_id or self._generate_id(), entity_type="room")

        # Create Identity component
        identity = StaticIdentityData(owner=entity_id)
        identity.name = template.name
        identity.short_description = template.short_description
        identity.long_description = template.long_description
        identity.keywords = [template.name.lower()]
        identity.template_id = template.template_id
        identity.zone_id = template.zone_id
        identity.vnum = template.vnum

        await self._register_component(entity_id, "Identity", identity)

        # Create Room component
        room = StaticRoomData(owner=entity_id)
        room.short_description = template.short_description
        room.long_description = template.long_description
        room.area_id = template.zone_id
        room.sector_type = template.sector_type
        room.ambient_messages = template.ambient_messages.copy()
        room.template_id = template.template_id
        room.zone_id = template.zone_id
        room.vnum = template.vnum
        room.respawn_interval_s = template.respawn_interval_s

        # Parse flags
        room.is_dark = "dark" in template.flags
        room.is_safe = "safe" in template.flags or "no_combat" in template.flags
        room.is_no_mob = "no_mob" in template.flags
        room.is_no_recall = "no_recall" in template.flags
        room.is_no_magic = "no_magic" in template.flags

        # Note: exits reference template IDs, will be resolved after all rooms loaded
        room.respawn_mobs = [s.get("template_id", s.get("mob", "")) for s in template.mob_spawns]
        room.respawn_items = [s.get("template_id", s.get("item", "")) for s in template.item_spawns]

        await self._register_component(entity_id, "Room", room)

        logger.debug(f"Created room: {template_id} -> {entity_id}")
        return entity_id

    # =========================================================================
    # Mob Creation
    # =========================================================================

    async def create_mob(
        self, template_id: str, room_id: Optional[EntityId] = None
    ) -> Optional[EntityId]:
        """
        Create a mob entity from template.
        """
        template = self.registry.get_mob(template_id)
        if not template:
            logger.error(f"Mob template not found: {template_id}")
            return None

        entity_id = EntityId(id=self._generate_id(), entity_type="mob")

        # Identity
        identity = StaticIdentityData(owner=entity_id)
        identity.name = template.name
        identity.keywords = (
            template.keywords.copy() if template.keywords else [template.name.lower()]
        )
        identity.short_description = template.short_description or f"{template.name} is here."
        identity.long_description = template.long_description
        identity.template_id = template.template_id
        identity.zone_id = template.zone_id
        identity.vnum = template.vnum

        await self._register_component(entity_id, "Identity", identity)

        # Location
        location = LocationData(owner=entity_id)
        location.room_id = room_id

        await self._register_component(entity_id, "Location", location)

        # Stats
        stats = MobStatsData(owner=entity_id)
        stats.attributes = AttributeBlock(
            strength=template.strength,
            dexterity=template.dexterity,
            constitution=template.constitution,
            intelligence=template.intelligence,
            wisdom=template.wisdom,
            charisma=template.charisma,
        )
        stats.max_health = template.health
        stats.current_health = template.health
        stats.max_mana = template.mana
        stats.current_mana = template.mana
        stats.armor_class = template.armor_class
        stats.attack_bonus = template.attack_bonus
        stats.challenge_rating = template.level
        stats.experience_value = template.experience_value
        stats.aggro_radius = template.aggro_radius
        stats.gold_min = template.gold_min
        stats.gold_max = template.gold_max

        await self._register_component(entity_id, "Stats", stats)

        # Combat
        combat = CombatData(owner=entity_id)
        combat.weapon_damage_dice = template.damage_dice
        combat.weapon_damage_type = template.damage_type

        await self._register_component(entity_id, "Combat", combat)

        # AI
        ai = StaticAIData(owner=entity_id)
        ai.template_id = template.template_id
        ai.behavior_type = template.behavior_type
        ai.combat_style = template.combat_style
        ai.aggro_radius = template.aggro_radius
        ai.flee_threshold = template.flee_threshold
        ai.home_room = room_id

        await self._register_component(entity_id, "AI", ai)

        # Inventory (for loot)
        inventory = ContainerData(owner=entity_id)

        await self._register_component(entity_id, "Container", inventory)

        # Dialogue if present
        if template.dialogue:
            dialogue = DialogueData(owner=entity_id)
            dialogue.greeting = template.dialogue.get("greeting", "")
            dialogue.farewell = template.dialogue.get("farewell", "")
            dialogue.topics = {
                k: v for k, v in template.dialogue.items() if k not in ("greeting", "farewell")
            }
            dialogue.is_quest_giver = "quest_giver" in template.flags
            dialogue.is_merchant = "merchant" in template.flags
            dialogue.is_trainer = "trainer" in template.flags

            await self._register_component(entity_id, "Dialogue", dialogue)

        logger.debug(f"Created mob: {template_id} -> {entity_id}")
        return entity_id

    # =========================================================================
    # Item Creation
    # =========================================================================

    async def create_item(
        self,
        template_id: str,
        container_id: Optional[EntityId] = None,
        room_id: Optional[EntityId] = None,
    ) -> Optional[EntityId]:
        """
        Create an item entity from template.
        """
        template = self.registry.get_item(template_id)
        if not template:
            logger.error(f"Item template not found: {template_id}")
            return None

        entity_id = EntityId(id=self._generate_id(), entity_type="item")

        # Identity
        identity = StaticIdentityData(owner=entity_id)
        identity.name = template.name
        identity.keywords = (
            template.keywords.copy() if template.keywords else [template.name.lower()]
        )
        identity.short_description = template.short_description or f"{template.name} is here."
        identity.long_description = template.long_description
        identity.template_id = template.template_id
        identity.zone_id = template.zone_id
        identity.vnum = template.vnum

        await self._register_component(entity_id, "Identity", identity)

        # Location (if on ground in room)
        if room_id:
            location = LocationData(owner=entity_id)
            location.room_id = room_id
            await self._register_component(entity_id, "Location", location)

        # Base item data
        item = ItemData(owner=entity_id)
        item.item_type = template.item_type
        item.rarity = template.rarity
        item.weight = template.weight
        item.value = template.value
        item.level_requirement = template.level_requirement
        item.is_quest_item = "quest" in template.flags
        item.is_cursed = "cursed" in template.flags
        item.is_bound = "bound" in template.flags or "no_drop" in template.flags

        await self._register_component(entity_id, "Item", item)

        # Weapon data
        if template.damage_dice and template.item_type == ItemType.WEAPON:
            weapon = WeaponData(owner=entity_id)
            weapon.damage_dice = template.damage_dice
            weapon.damage_type = template.damage_type or DamageType.SLASHING
            weapon.weapon_type = template.weapon_type or WeaponType.SWORD
            weapon.two_handed = template.two_handed
            weapon.hit_bonus = template.hit_bonus
            weapon.damage_bonus = template.damage_bonus

            await self._register_component(entity_id, "Weapon", weapon)

        # Armor data
        if template.armor_bonus > 0 or template.item_type == ItemType.ARMOR:
            armor = ArmorData(owner=entity_id)
            armor.armor_bonus = template.armor_bonus
            armor.armor_type = template.armor_type or ArmorType.LIGHT
            if template.equipment_slot:
                armor.slot = template.equipment_slot

            await self._register_component(entity_id, "Armor", armor)

        # Consumable data
        if template.effect_type:
            consumable = ConsumableData(owner=entity_id)
            consumable.effect_type = template.effect_type
            consumable.effect_value = template.effect_value
            consumable.uses_remaining = template.uses
            consumable.max_uses = template.uses

            await self._register_component(entity_id, "Consumable", consumable)

        logger.debug(f"Created item: {template_id} -> {entity_id}")
        return entity_id

    # =========================================================================
    # Player Creation
    # =========================================================================

    async def create_player(
        self,
        name: str,
        class_name: str = "adventurer",
        race_name: str = "human",
        account_id: str = "",
        start_room_id: Optional[EntityId] = None,
    ) -> EntityId:
        """
        Create a new player entity.
        """
        entity_id = EntityId(id=self._generate_id(), entity_type="player")

        # Identity
        identity = StaticIdentityData(owner=entity_id)
        identity.name = name
        identity.keywords = [name.lower()]
        identity.short_description = f"{name} is here."
        identity.article = ""  # Players don't have articles

        await self._register_component(entity_id, "Identity", identity)

        # Location
        location = LocationData(owner=entity_id)
        location.room_id = start_room_id

        await self._register_component(entity_id, "Location", location)

        # Stats
        stats = PlayerStatsData(owner=entity_id)
        stats.class_name = class_name
        stats.race_name = race_name
        stats.level = 1
        stats.experience = 0
        stats.experience_to_level = 1000
        stats.max_health = 100
        stats.current_health = 100
        stats.max_mana = 50
        stats.current_mana = 50

        await self._register_component(entity_id, "Stats", stats)

        # Combat
        combat = CombatData(owner=entity_id)
        combat.weapon_damage_dice = "1d4"  # Unarmed

        await self._register_component(entity_id, "Combat", combat)

        # Inventory
        inventory = ContainerData(owner=entity_id)
        inventory.max_items = 30
        inventory.max_weight = 200.0

        await self._register_component(entity_id, "Container", inventory)

        # Equipment
        equipment = EquipmentSlotsData(owner=entity_id)

        await self._register_component(entity_id, "Equipment", equipment)

        # Connection (will be updated when player connects)
        connection = PlayerConnectionData(owner=entity_id)
        connection.account_id = account_id

        await self._register_component(entity_id, "Connection", connection)

        # Progress
        progress = PlayerProgressData(owner=entity_id)
        progress.account_id = account_id
        progress.character_name = name

        await self._register_component(entity_id, "Progress", progress)

        # Quest log
        quests = QuestLogData(owner=entity_id)

        await self._register_component(entity_id, "QuestLog", quests)

        logger.info(f"Created player: {name} -> {entity_id}")
        return entity_id

    # =========================================================================
    # Portal Creation
    # =========================================================================

    async def create_portal(self, template_id: str, room_id: EntityId) -> Optional[EntityId]:
        """
        Create a portal entity from template.
        """
        template = self.registry.get_portal(template_id)
        if not template:
            logger.error(f"Portal template not found: {template_id}")
            return None

        entity_id = EntityId(id=self._generate_id(), entity_type="portal")

        # Identity
        identity = StaticIdentityData(owner=entity_id)
        identity.name = template.name
        identity.keywords = (
            template.keywords.copy() if template.keywords else [template.name.lower(), "portal"]
        )
        identity.short_description = template.description
        identity.template_id = template.template_id

        await self._register_component(entity_id, "Identity", identity)

        # Location
        location = LocationData(owner=entity_id)
        location.room_id = room_id

        await self._register_component(entity_id, "Location", location)

        # Portal data
        portal = PortalData(owner=entity_id)
        portal.portal_id = template.template_id
        portal.name = template.name
        portal.description = template.description
        portal.theme_id = template.theme_id
        portal.theme_description = template.theme_description
        portal.instance_type = InstanceType(template.instance_type)
        portal.difficulty_min = template.difficulty_min
        portal.difficulty_max = template.difficulty_max
        portal.max_rooms = template.max_rooms
        portal.max_players = template.max_players
        portal.cooldown_s = template.cooldown_s
        portal.min_level = template.min_level
        portal.required_items = template.required_items.copy()

        await self._register_component(entity_id, "Portal", portal)

        logger.debug(f"Created portal: {template_id} -> {entity_id}")
        return entity_id


# Global factory instance
_factory: Optional[EntityFactory] = None


def get_entity_factory() -> EntityFactory:
    """Get the global entity factory (local registry)."""
    global _factory
    if _factory is None:
        _factory = EntityFactory()
    return _factory


class DistributedEntityFactory:
    """
    Creates entities from templates stored in the distributed registry.

    This is the preferred factory for multi-process deployments where
    templates are registered to the TemplateRegistryActor.
    """

    def __init__(
        self,
        component_engine: Optional[ActorHandle] = None,
        entity_index: Optional[ActorHandle] = None,
    ):
        self._component_engine = component_engine
        self._entity_index = entity_index
        self._registry_actor = None

    def _get_registry(self) -> ActorHandle:
        """Get template registry actor lazily."""
        if self._registry_actor is None:
            self._registry_actor = get_template_registry_actor()
        return self._registry_actor

    def _get_component_engine(self) -> ActorHandle:
        """Get component engine lazily."""
        if self._component_engine is None:
            self._component_engine = core_component_engine()
        return self._component_engine

    def _get_entity_index(self) -> ActorHandle:
        """Get entity index lazily."""
        if self._entity_index is None:
            self._entity_index = core_entity_index()
        return self._entity_index

    def _generate_id(self) -> str:
        """Generate a unique entity instance ID."""
        return uuid.uuid4().hex[:12]

    async def _register_component(
        self, entity: EntityId, component_type: str, data: ComponentData
    ) -> None:
        """Register a component for an entity."""
        from core.component import get_component_actor

        try:
            actor = get_component_actor(component_type)
            await actor.create.remote(entity, lambda c: self._copy_data(c, data))
            index = self._get_entity_index()
            await index.register.remote(entity, component_type)
        except Exception as e:
            logger.error(f"Error registering component {component_type} for {entity}: {e}")
            raise

    def _copy_data(self, target: ComponentData, source: ComponentData) -> None:
        """Copy data from source to target component."""
        for f in fields(source):
            if f.name != "owner":
                setattr(target, f.name, getattr(source, f.name))

    async def create_room(
        self, template_id: str, instance_id: Optional[str] = None
    ) -> Optional[EntityId]:
        """Create a room entity from distributed template."""
        template = await self._get_registry().get_room.remote(template_id)
        if not template:
            logger.error(f"Room template not found: {template_id}")
            return None

        entity_id = EntityId(id=instance_id or self._generate_id(), entity_type="room")

        # Create Identity component
        identity = StaticIdentityData(owner=entity_id)
        identity.name = template.name
        identity.short_description = template.short_description
        identity.long_description = template.long_description
        identity.keywords = [template.name.lower()]
        identity.template_id = template.template_id
        identity.zone_id = template.zone_id
        identity.vnum = template.vnum

        await self._register_component(entity_id, "Identity", identity)

        # Create Room component
        room = StaticRoomData(owner=entity_id)
        room.short_description = template.short_description
        room.long_description = template.long_description
        room.area_id = template.zone_id
        room.sector_type = template.sector_type
        room.ambient_messages = template.ambient_messages.copy()
        room.template_id = template.template_id
        room.zone_id = template.zone_id
        room.vnum = template.vnum
        room.respawn_interval_s = template.respawn_interval_s

        room.is_dark = "dark" in template.flags
        room.is_safe = "safe" in template.flags or "no_combat" in template.flags
        room.is_no_mob = "no_mob" in template.flags
        room.is_no_recall = "no_recall" in template.flags
        room.is_no_magic = "no_magic" in template.flags

        room.respawn_mobs = [s.get("template_id", s.get("mob", "")) for s in template.mob_spawns]
        room.respawn_items = [s.get("template_id", s.get("item", "")) for s in template.item_spawns]

        await self._register_component(entity_id, "Room", room)

        logger.debug(f"Created room (distributed): {template_id} -> {entity_id}")
        return entity_id

    async def create_mob(
        self, template_id: str, room_id: Optional[EntityId] = None
    ) -> Optional[EntityId]:
        """Create a mob entity from distributed template."""
        template = await self._get_registry().get_mob.remote(template_id)
        if not template:
            logger.error(f"Mob template not found: {template_id}")
            return None

        entity_id = EntityId(id=self._generate_id(), entity_type="mob")

        # Identity
        identity = StaticIdentityData(owner=entity_id)
        identity.name = template.name
        identity.keywords = (
            template.keywords.copy() if template.keywords else [template.name.lower()]
        )
        identity.short_description = template.short_description or f"{template.name} is here."
        identity.long_description = template.long_description
        identity.template_id = template.template_id
        identity.zone_id = template.zone_id
        identity.vnum = template.vnum

        await self._register_component(entity_id, "Identity", identity)

        # Location
        location = LocationData(owner=entity_id)
        location.room_id = room_id

        await self._register_component(entity_id, "Location", location)

        # Stats
        stats = MobStatsData(owner=entity_id)
        stats.attributes = AttributeBlock(
            strength=template.strength,
            dexterity=template.dexterity,
            constitution=template.constitution,
            intelligence=template.intelligence,
            wisdom=template.wisdom,
            charisma=template.charisma,
        )
        stats.max_health = template.health
        stats.current_health = template.health
        stats.max_mana = template.mana
        stats.current_mana = template.mana
        stats.armor_class = template.armor_class
        stats.attack_bonus = template.attack_bonus
        stats.challenge_rating = template.level
        stats.experience_value = template.experience_value
        stats.aggro_radius = template.aggro_radius
        stats.gold_min = template.gold_min
        stats.gold_max = template.gold_max

        await self._register_component(entity_id, "Stats", stats)

        # Combat
        combat = CombatData(owner=entity_id)
        combat.weapon_damage_dice = template.damage_dice
        combat.weapon_damage_type = template.damage_type

        await self._register_component(entity_id, "Combat", combat)

        # AI
        ai = StaticAIData(owner=entity_id)
        ai.template_id = template.template_id
        ai.behavior_type = template.behavior_type
        ai.combat_style = template.combat_style
        ai.aggro_radius = template.aggro_radius
        ai.flee_threshold = template.flee_threshold
        ai.home_room = room_id

        await self._register_component(entity_id, "AI", ai)

        # Inventory (for loot)
        inventory = ContainerData(owner=entity_id)
        await self._register_component(entity_id, "Container", inventory)

        # Dialogue if present
        if template.dialogue:
            dialogue = DialogueData(owner=entity_id)
            dialogue.greeting = template.dialogue.get("greeting", "")
            dialogue.farewell = template.dialogue.get("farewell", "")
            dialogue.topics = {
                k: v for k, v in template.dialogue.items() if k not in ("greeting", "farewell")
            }
            dialogue.is_quest_giver = "quest_giver" in template.flags
            dialogue.is_merchant = "merchant" in template.flags
            dialogue.is_trainer = "trainer" in template.flags

            await self._register_component(entity_id, "Dialogue", dialogue)

        logger.debug(f"Created mob (distributed): {template_id} -> {entity_id}")
        return entity_id

    async def create_item(
        self,
        template_id: str,
        container_id: Optional[EntityId] = None,
        room_id: Optional[EntityId] = None,
    ) -> Optional[EntityId]:
        """Create an item entity from distributed template."""
        template = await self._get_registry().get_item.remote(template_id)
        if not template:
            logger.error(f"Item template not found: {template_id}")
            return None

        entity_id = EntityId(id=self._generate_id(), entity_type="item")

        # Identity
        identity = StaticIdentityData(owner=entity_id)
        identity.name = template.name
        identity.keywords = (
            template.keywords.copy() if template.keywords else [template.name.lower()]
        )
        identity.short_description = template.short_description or f"{template.name} is here."
        identity.long_description = template.long_description
        identity.template_id = template.template_id
        identity.zone_id = template.zone_id
        identity.vnum = template.vnum

        await self._register_component(entity_id, "Identity", identity)

        # Location (if on ground in room)
        if room_id:
            location = LocationData(owner=entity_id)
            location.room_id = room_id
            await self._register_component(entity_id, "Location", location)

        # Base item data
        item = ItemData(owner=entity_id)
        item.item_type = template.item_type
        item.rarity = template.rarity
        item.weight = template.weight
        item.value = template.value
        item.level_requirement = template.level_requirement
        item.is_quest_item = "quest" in template.flags
        item.is_cursed = "cursed" in template.flags
        item.is_bound = "bound" in template.flags or "no_drop" in template.flags

        await self._register_component(entity_id, "Item", item)

        # Weapon data
        if template.damage_dice and template.item_type == ItemType.WEAPON:
            weapon = WeaponData(owner=entity_id)
            weapon.damage_dice = template.damage_dice
            weapon.damage_type = template.damage_type or DamageType.SLASHING
            weapon.weapon_type = template.weapon_type or WeaponType.SWORD
            weapon.two_handed = template.two_handed
            weapon.hit_bonus = template.hit_bonus
            weapon.damage_bonus = template.damage_bonus

            await self._register_component(entity_id, "Weapon", weapon)

        # Armor data
        if template.armor_bonus > 0 or template.item_type == ItemType.ARMOR:
            armor = ArmorData(owner=entity_id)
            armor.armor_bonus = template.armor_bonus
            armor.armor_type = template.armor_type or ArmorType.LIGHT
            if template.equipment_slot:
                armor.slot = template.equipment_slot

            await self._register_component(entity_id, "Armor", armor)

        # Consumable data
        if template.effect_type:
            consumable = ConsumableData(owner=entity_id)
            consumable.effect_type = template.effect_type
            consumable.effect_value = template.effect_value
            consumable.uses_remaining = template.uses
            consumable.max_uses = template.uses

            await self._register_component(entity_id, "Consumable", consumable)

        logger.debug(f"Created item (distributed): {template_id} -> {entity_id}")
        return entity_id

    async def create_player(
        self,
        name: str,
        class_name: str = "adventurer",
        race_name: str = "human",
        account_id: str = "",
        start_room_id: Optional[EntityId] = None,
    ) -> EntityId:
        """Create a new player entity (same as local factory)."""
        entity_id = EntityId(id=self._generate_id(), entity_type="player")

        # Identity
        identity = StaticIdentityData(owner=entity_id)
        identity.name = name
        identity.keywords = [name.lower()]
        identity.short_description = f"{name} is here."
        identity.article = ""

        await self._register_component(entity_id, "Identity", identity)

        # Location
        location = LocationData(owner=entity_id)
        location.room_id = start_room_id

        await self._register_component(entity_id, "Location", location)

        # Stats
        stats = PlayerStatsData(owner=entity_id)
        stats.class_name = class_name
        stats.race_name = race_name
        stats.level = 1
        stats.experience = 0
        stats.experience_to_level = 1000
        stats.max_health = 100
        stats.current_health = 100
        stats.max_mana = 50
        stats.current_mana = 50

        await self._register_component(entity_id, "Stats", stats)

        # Combat
        combat = CombatData(owner=entity_id)
        combat.weapon_damage_dice = "1d4"

        await self._register_component(entity_id, "Combat", combat)

        # Inventory
        inventory = ContainerData(owner=entity_id)
        inventory.max_items = 30
        inventory.max_weight = 200.0

        await self._register_component(entity_id, "Container", inventory)

        # Equipment
        equipment = EquipmentSlotsData(owner=entity_id)
        await self._register_component(entity_id, "Equipment", equipment)

        # Connection
        connection = PlayerConnectionData(owner=entity_id)
        connection.account_id = account_id

        await self._register_component(entity_id, "Connection", connection)

        # Progress
        progress = PlayerProgressData(owner=entity_id)
        progress.account_id = account_id
        progress.character_name = name

        await self._register_component(entity_id, "Progress", progress)

        # Quest log
        quests = QuestLogData(owner=entity_id)
        await self._register_component(entity_id, "QuestLog", quests)

        logger.info(f"Created player (distributed): {name} -> {entity_id}")
        return entity_id

    async def create_portal(self, template_id: str, room_id: EntityId) -> Optional[EntityId]:
        """Create a portal entity from distributed template."""
        template = await self._get_registry().get_portal.remote(template_id)
        if not template:
            logger.error(f"Portal template not found: {template_id}")
            return None

        entity_id = EntityId(id=self._generate_id(), entity_type="portal")

        # Identity
        identity = StaticIdentityData(owner=entity_id)
        identity.name = template.name
        identity.keywords = (
            template.keywords.copy() if template.keywords else [template.name.lower(), "portal"]
        )
        identity.short_description = template.description
        identity.template_id = template.template_id

        await self._register_component(entity_id, "Identity", identity)

        # Location
        location = LocationData(owner=entity_id)
        location.room_id = room_id

        await self._register_component(entity_id, "Location", location)

        # Portal data
        portal = PortalData(owner=entity_id)
        portal.portal_id = template.template_id
        portal.name = template.name
        portal.description = template.description
        portal.theme_id = template.theme_id
        portal.theme_description = template.theme_description
        portal.instance_type = InstanceType(template.instance_type)
        portal.difficulty_min = template.difficulty_min
        portal.difficulty_max = template.difficulty_max
        portal.max_rooms = template.max_rooms
        portal.max_players = template.max_players
        portal.cooldown_s = template.cooldown_s
        portal.min_level = template.min_level
        portal.required_items = template.required_items.copy()

        await self._register_component(entity_id, "Portal", portal)

        logger.debug(f"Created portal (distributed): {template_id} -> {entity_id}")
        return entity_id


# Global distributed factory instance
_distributed_factory: Optional[DistributedEntityFactory] = None


def get_distributed_entity_factory() -> DistributedEntityFactory:
    """Get the global distributed entity factory."""
    global _distributed_factory
    if _distributed_factory is None:
        _distributed_factory = DistributedEntityFactory()
    return _distributed_factory
