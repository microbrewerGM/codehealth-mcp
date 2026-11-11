"""A small, healthy module."""

from dataclasses import dataclass


@dataclass
class Counter:
    count: int = 0

    def increment(self, step: int = 1) -> int:
        self.count += step
        return self.count

    def reset(self) -> None:
        self.count = 0


def greet(name: str) -> str:
    if not name:
        return "Hello, stranger"
    return f"Hello, {name}"


def total(values: list[int]) -> int:
    return sum(v for v in values if v > 0)
