import abc
from enum import Enum

class Entity(abc.ABC):
    @property
    @abc.abstractmethod
    def entity_id(self):
        pass


class Direction(Enum):
    NORTH = 0
    NORTHEAST = 1
    EAST = 2
    SOUTHEAST = 3
    SOUTH = 4
    SOUTHWEST = 5
    WEST = 6
    NORTHWEST = 7