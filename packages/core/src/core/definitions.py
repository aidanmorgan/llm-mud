from typing import Optional, List


class SystemDefinition:
    def __init__(self, name: str, node_id: str, component: str | List[str]):
        self._name = name
        self._node_id = node_id

        if isinstance(component, list):
            self._components = component
        else:
            self._components = [component]

    @property
    def name(self) -> str:
        return self._name

    @property
    def node_id(self) -> str:
        return self._node_id


class EntityDefinition:
    def __init__(self, name: str, parent: Optional[str] = None):
        self._name = name
        self._parent = parent

    @property
    def name(self) -> str:
        return self._name

    @property
    def parent(self) -> Optional[str]:
        return self._parent


class ComponentDefinition:
    def __init__(self, name: str, node: str, fields: Optional[str | List[str]] = None):
        self._name = name
        self._node = node

        if fields and isinstance(fields, list):
            self._fields = fields
        elif fields:
            self._fields = [fields]
        else:
            self._fields = list()

    @property
    def name(self) -> str:
        return self._name
