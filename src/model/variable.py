import abc

from model.context import Context


class RandomVariable(abc.ABC):
    @abc.abstractmethod
    def next_value(self, ctx: Context) -> int:
        pass


class NormalRandomVariable(RandomVariable):
    def __init__(self, mean: int, stdev: int):
        self._mean = mean
        self._stdev = stdev

    def next_value(self, ctx: Context) -> int:
        pass


class UniformRandomVariable:
    def __init__(self, minimum: int, maximum: int):
        self.minimum = minimum
        self.maximum = maximum

    def next_value(self, ctx: Context) -> int:
        return int(ctx._random.uniform(self.minimum, self.maximum))


class TemplateString(abc.ABC):
    @abc.abstractmethod
    def next_value(self, ctx: Context) -> str:
        pass


class FixedString(TemplateString):
    def __init__(self, value: str):
        self._value = value

    def next_value(self, ctx: Context) -> str:
        return self._value


class JinjaString(TemplateString):
    def __init__(self, template: str):
        self._template = template

    def next_value(self, ctx: Context) -> str:
        return self._template

class LlmString(TemplateString):
    pass
