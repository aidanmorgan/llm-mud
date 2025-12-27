import abc
import uuid
from abc import abstractmethod
from typing import List

from .definitions import SystemDefinition, EntityDefinition, ComponentDefinition
from .identifiers import EntityId


class Node(abc.ABC):
    def __init__(self, id: str = None):
        self._id = id or uuid.uuid4().hex

    @abstractmethod
    async def connect(self):
        pass

    @abstractmethod
    async def disconnect(self):
        pass

    @abstractmethod
    async def register_system(self, sd: SystemDefinition) -> str:
        pass

    @abstractmethod
    async def register_component(self, cd: ComponentDefinition) -> str:
        pass

    @abstractmethod
    async def create_entity(self, ed: EntityDefinition) -> EntityId:
        pass

    @abstractmethod
    async def get_entities(self, type: str, parent: str = None) -> List[EntityId]:
        pass

    async def subscribe_entities(self) -> None:
        pass
