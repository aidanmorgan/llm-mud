from typing import List, Optional

from core.definitions import EntityDefinition


class EntityId:
    def __init__(
        self,
        instance_id: str,
        entity: EntityDefinition,
        id: str,
        component: str | List[str],
    ):
        self._id = instance_id
        self._entity_definition = entity

        if isinstance(component, list):
            self._components = component
        else:
            self._components = [component]

    @property
    def entity_type(self) -> str:
        return self._entity_definition.name

    @property
    def parent_type(self) -> Optional[str]:
        return self._entity_definition.parent

    @property
    def id(self) -> str:
        return self._id
