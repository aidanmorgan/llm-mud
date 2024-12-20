import abc
import random
import uuid
from enum import Enum
from typing import Optional

from model.level import VirtualSector


class Scope(Enum):
    GAME = 1
    SECTOR = 2
    ROOM = 4
    PLAYER = 8
    MOBILE = 16
    ITEM = 32
    CONTAINER = 64


class Context(abc.ABC):
    @abc.abstractmethod
    def scope(self) -> Scope:
        pass

    @abc.abstractmethod
    def create_id(self) -> str:
        pass


class GameContext(Context):
    def scope(self) -> Scope:
        return Scope.GAME

    def __init__(self):
        self._sectors = dict[str, 'Sector']()
        self._rooms = dict[str, 'Room']()
        self._sector_templates = dict[str, 'SectorTemplate']()
        self._room_templates = dict[str, 'RoomTemplate']()
        self._item_templates = dict[str, 'ItemTemplate']()
        self._mobile_templates = dict[str, 'MobileTemplate']()

        self._items = dict[str, 'Item']()
        self._item_templates = dict[str, 'ItemTemplate']()

        self._mobiles = dict[str, 'Mobile']()
        self._mobile_templates = dict[str, 'MobileTemplate']()

        self._random = random.SystemRandom()

    def create_id(self) -> str:
        return uuid.uuid4().hex

    def get_sector_by_id(self, sector_id: str) -> Optional['Sector']:
        pass

    def get_room_by_id(self, room_id: str) -> Optional['Room']:
        pass

    def get_item_by_id(self, item_id: str) -> Optional['Item']:
        pass

    def get_mobile_by_id(self, mobile_id: str) -> Optional['Mobile']:
        pass

    def create_sector(self, template_id: str) -> Optional['Sector']:
        pass

    def create_room(self, template_id: str) -> Optional['Room']:
        pass

    def create_item(self, template_id: str) -> Optional['Item']:
        pass

    def create_mobile(self, template_id: str) -> Optional['Mobile']:
        pass

    def rand(self, minimum: int = None, maximum: int = None) -> int:
        pass

    def register_item(self, entity_id: str, item: 'Item'):
        self._items[entity_id] = item

    def register_mobile(self, entity_id: str, mobile: 'Mobile'):
        self._mobiles[entity_id] = mobile

    def register_room(self, entity_id: str, room: 'Room'):
        self._rooms[entity_id] = room

    def register_sector(self, entity_id: str, sector: 'Sector') -> 'SectorContext':
        self._sectors[entity_id] = sector


class SectorContext(Context):
    def scope(self) -> Scope:
        return Scope.SECTOR

    def __init__(self, gc: GameContext, s: 'Sector'):
        self._game_context = gc
        self._sector = s

    @property
    def game(self) -> GameContext:
        return self._game_context

    @property
    def sector(self) -> 'Sector':
        return self._sector


class RoomContext(Context):
    def scope(self) -> Scope:
        return Scope.ROOM

    def __init__(self, gc: GameContext, s: SectorContext, r: 'Room'):
        self._game_context = gc
        self._sector_context = s
        self._room = r

    @property
    def game(self) -> GameContext:
        return self._game_context

    @property
    def sector(self) -> SectorContext:
        return self._sector_context

    @property
    def room(self) -> 'Room':
        return self._room


class PlayerContext(Context):
    def scope(self) -> Scope:
        return Scope.PLAYER

    def __init__(self, gc: RoomContext, p: 'Player'):
        self._room_context = gc
        self._player = p

    @property
    def game_context(self) -> GameContext:
        return self._room_context.game

    @property
    def sector_context(self) -> SectorContext:
        return self._room_context.sector

    @property
    def room_context(self) -> RoomContext:
        pass

    @property
    def player(self) -> 'Player':
        return self._player


class ItemContext(Context):
    def scope(self) -> Scope:
        return Scope.ITEM

    def __init__(self, rc: RoomContext = None, pc: PlayerContext = None, i: 'Item' = None):
        self._room_context = rc
        self._player_context = pc
        self._item = i

    @property
    def game(self) -> GameContext:
        return self._room_context.game

    @property
    def sector(self) -> SectorContext:
        return self._room_context.sector

    @property
    def room(self) -> RoomContext:
        return self._room_context

    @property
    def item(self) -> 'Item':
        return self._item


class MobileContext(Context):
    def scope(self) -> Scope:
        return Scope.MOBILE

    def __init__(self, rc: RoomContext, mobile: 'Mobile'):
        self._room_context = rc
        self._mobile = mobile

