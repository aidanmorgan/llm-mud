import abc

from model.core import Entity, MobileContext


class Mobile(abc.ABC, Entity):
    pass

class MobileTemplate:
    def create_mobile(self, ctx: GameContext) -> Mobile:
        pass