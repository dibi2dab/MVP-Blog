from __future__ import annotations

from src.config.settings import Settings
from src.publishers.base import (
    BasePublisher,
    LocalPublisher,
    MockPublisher,
    PublishDeduplicator,
)
from src.publishers.tistory_publisher import TistoryPublisher
from src.publishers.node_tistory_publisher import NodeTistoryPublisher
from src.storage.file_store import JsonStore
from src.utils.logging import get_logger

logger = get_logger(__name__)


class PublisherFactory:
    def __init__(self, settings: Settings, store: JsonStore) -> None:
        self.settings = settings
        self.store = store

    def build(self, backend: str | None = None) -> BasePublisher:
        backend = (backend or self.settings.effective_backend or "local").lower()
        if backend == "mock":
            return MockPublisher(self.settings, self.store)
        if backend == "local":
            return LocalPublisher(self.settings, self.store)
        if backend == "tistory":
            return TistoryPublisher(self.settings, self.store)
        if backend in ("tistory-node", "tistory_node", "node"):
            return NodeTistoryPublisher(self.settings, self.store)
        raise ValueError(f"unsupported publish backend: {backend}")