import abc
from typing import Dict, List

from model.core import Entity, Direction


class Sector(abc.ABC, Entity):
    @property
    @abc.abstractmethod
    def connections(self) -> Dict[str, 'Connection']:
        pass

    @property
    @abc.abstractmethod
    def rooms(self) -> Dict[str, 'Room']:
        pass


class VirtualSectorTemplate:
    def create_sector(self, ctx: GameContext) -> 'VirtualSector':
        pass

class VirtualSector(Sector):
    def __init__(self, template_id:str, context: GameContext):
        self._template_id = template_id
        self._game_context = context

    @property
    def template_id(self) -> str:
        return self._template_id


class FixedSector(Sector):
    pass


class Room(abc.ABC, Entity):
    """
    A Room contains Items, Mobiles and Players
    """
    @property
    @abc.abstractmethod
    def portals(self) -> Dict[Direction, 'Connection']:
        pass

class VirtualRoomTemplate:
    def create_room(self, ctx: GameContext) -> 'Room':
        pass

class VirtualRoom(Room):
    pass

class FixedRoom(Room):
    pass

class Connection(abc.ABC):
    pass

class Door(Connection):
    pass

class Portal(Connection):
    pass