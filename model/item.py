from model.context import Context
from model.core import Entity
from model.effect import Effect, Effectable


class Item(Entity, Effectable):
    def __init__(self, owner: Context):
        self._context = owner
        self._entity_id = None
        self._title = None
        self._description = None
        self._weight = 0
        self._effects = list[Effect]()

    @property
    def entity_id(self):
        return self._entity_id

    @property
    def title(self):
        return self._title

    @title.setter
    def title(self, val: str):
        self._title = val

    @property
    def description(self):
        return self._description

    @property
    def weight(self):
        return self._weight

    def has_effect(self, id: str) -> bool:
        pass

    def add_effect(self, ctx: Context, effect: str):
        pass

    def remove_effect(self, ctx: Context, effect: str):
        pass


class ItemTemplate:
    def __init__(self, **kwargs):
        self._title = kwargs.get('title')
        self._weight = kwargs.get('weight')
        self._value = kwargs.get('value')

    def create_item(self, ctx: Context) -> Item:
        item: Item = Item(ctx)
        item._entity_id = ctx.create_id()
        item.title = self._weight.next_value(ctx)

        ctx.register_item(item.entity_id, item)

        return item


class Weapon(Item):
    def __init__(self, ctx: Context):
        pass

class WeaponTemplate:
    def __init__(self, **kwargs):
        self._title = kwargs.get('title')
        self._weight = kwargs.get('weight')
        self._value = kwargs.get('value')
        self._attack_points = kwargs.get('attack_points')

    def create_weapon(self, ctx: Context) -> Weapon:
        return None