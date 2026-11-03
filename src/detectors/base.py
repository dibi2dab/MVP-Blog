from __future__ import annotations

from abc import ABC, abstractmethod

from src.models.event import Event


class BaseDetector(ABC):
    name: str = "base"

    @abstractmethod
    def detect(self, *args, **kwargs) -> list[Event]:
        raise NotImplementedError