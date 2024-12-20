import abc

from model.core import Entity


class Player(abc.ABC, Entity):
    def __init__(self):
        self._inventory = dict[str, Item]()
