import abc

from model.context import Context


class Effect(abc.ABC):
    pass


class Effectable(abc.ABC):
    @abc.abstractmethod
    def has_effect(self, id: str) -> bool:
        pass

    @abc.abstractmethod
    def add_effect(self, ctx: Context, effect: str):
        pass

    @abc.abstractmethod
    def remove_effect(self, ctx: Context, effect: str):
        pass
