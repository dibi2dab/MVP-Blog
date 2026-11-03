from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    def load_dotenv(*args: Any, **kwargs: Any) -> None:
        return None


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_DIR = PROJECT_ROOT / "config"


class AppConfig(BaseModel):
    name: str = "finance-research-blog"
    timezone: str = "Asia/Seoul"
    mock_mode: str = "auto"
    log_level: str = "INFO"


class StorageConfig(BaseModel):
    base_dir: str = "data"
    raw_dir: str = "raw"
    normalized_dir: str = "normalized"
    events_dir: str = "events"
    research_dir: str = "research"
    cache_dir: str = "cache"
    processed_dir: str = "processed"
    published_dir: str = "published"

    @property
    def base_path(self) -> Path:
        p = Path(self.base_dir)
        return p if p.is_absolute() else PROJECT_ROOT / p

    def path(self, key: str) -> Path:
        return self.base_path / getattr(self, f"{key}_dir")


class ContentConfig(BaseModel):
    output_dir: str = "content"
    categories: dict[str, str] = Field(default_factory=lambda: {"stocks": "stocks"})


class ChartConfig(BaseModel):
    output_dir: str = "static/charts"
    width: int = 12
    height: int = 7
    dpi: int = 120


class AIConfig(BaseModel):
    provider: str = "auto"
    model: str = "auto"
    temperature: float = 0.2
    max_tokens: int = 3000
    timeout_seconds: int = 120
    minimum_confidence: float = 0.75
    max_claims_per_article: int = 30
    cache_ttl_seconds: int = 3600


class ScoringConfig(BaseModel):
    minimum_research_score: int = 7
    minimum_publish_score: int = 8
    minimum_confidence: float = 0.75
    weights: dict[str, int] = Field(default_factory=dict)


class EvidenceConfig(BaseModel):
    """Evidence Score 계산 규칙. 근거가 얼마나 있는지를 점수화한다."""

    weights: dict[str, int] = Field(default_factory=dict)
    deep_analysis_threshold: int = 12   # 이 이상이면 Type A Deep Analysis
    data_brief_threshold: int = 5       # 이상 but 미만이면 Type B Data Brief
    reject_threshold: int = 0           # 근거/데이터 분석가치가 매우 낮으면 Type C


class DetectionConfig(BaseModel):
    price_change_high_threshold: float = 0.10
    price_change_mid_threshold: float = 0.05
    price_change_low_threshold: float = 0.03
    volume_surge_high_threshold: float = 3.0
    volume_surge_mid_threshold: float = 2.0
    volume_surge_low_threshold: float = 1.5
    min_volume_usd: int = 500_000_000
    lookback_days: int = 60
    max_events_per_run: int = 20


class NewsConfig(BaseModel):
    max_items: int = 40
    lookback_hours: int = 48
    dedupe_title_similarity: float = 0.85
    cluster_tolerance_minutes: int = 120


class ResearchConfig(BaseModel):
    max_news_per_entity: int = 15
    max_news_clusters: int = 5
    news_days: int = 7
    max_historical_cases: int = 5
    max_related_entities: int = 5


class MarkdownConfig(BaseModel):
    include_disclaimer: bool = True


class ContentQualityConfig(BaseModel):
    """기사 생성 품질 기준 (요구사항 5-7, 13)."""

    min_deep_chars: int = 1200
    min_data_brief_chars: int = 700
    min_paragraph_sentences: int = 2
    max_paragraph_sentences: int = 4
    banned_title_phrases: list[str] = Field(
        default_factory=lambda: [
            "데이터로 본 주가·거래량의 실체",
            "오늘 무슨 일이 있었나",
            "주가 움직임의 비밀",
            "전망",
        ]
    )
    # 각 주요 데이터를 FACT->CONTEXT->INTERPRETATION->LIMITATION 구조로 작성할 데이터 키
    data_card_fields: list[str] = Field(
        default_factory=lambda: ["price_change", "volume_change", "news", "disclosure"]
    )
    max_data_mentions: int = 3   # 동일 수치 최대 등장 횟수 (요구사항 10)


class PublishingConfig(BaseModel):
    backend: str = "local"
    content_dir: str = "content"
    images_base_url: str = "/charts"


class PublisherConfig(BaseModel):
    """최상위 publisher 설정. backend 타입을 지정한다."""

    type: str = "tistory"


class TistoryBrowserConfig(BaseModel):
    """Playwright 기반 티스토리 브라우저 발행 설정."""

    blog_url: str = ""
    editor_url: str = ""
    storage_state_path: str = ".state/tistory_storage_state.json"
    headless: bool = True
    default_visibility: str = "private"  # private | protected | public
    timeout: int = 30000
    screenshot_on_error: bool = True
    publish_delay_seconds: int = 2
    max_retries: int = 2
    dry_run: bool = False  # TISTORY_DRY_RUN=true
    selectors: dict[str, str] = Field(default_factory=dict)
    # 내부 카테고리(stocks/economy/...) ↔ 티스토리 메뉴명 매핑. 비면 해당 카테고리 미선택(기본).
    category_map: dict[str, str] = Field(default_factory=dict)

    def visibility_value(self) -> int:
        mapping = {"secret": 0, "private": 0, "protected": 1, "public": 3}
        return mapping.get(str(self.default_visibility).lower(), 0)


class SourceItemConfig(BaseModel):
    code: str
    name: str


class Settings(BaseModel):
    app: AppConfig = Field(default_factory=AppConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    content: ContentConfig = Field(default_factory=ContentConfig)
    charts: ChartConfig = Field(default_factory=ChartConfig)
    ai: AIConfig = Field(default_factory=AIConfig)
    scoring: ScoringConfig = Field(default_factory=ScoringConfig)
    evidence: EvidenceConfig = Field(default_factory=EvidenceConfig)
    detection: DetectionConfig = Field(default_factory=DetectionConfig)
    news: NewsConfig = Field(default_factory=NewsConfig)
    research: ResearchConfig = Field(default_factory=ResearchConfig)
    markdown: MarkdownConfig = Field(default_factory=MarkdownConfig)
    content_quality: ContentQualityConfig = Field(default_factory=ContentQualityConfig)
    publishing: PublishingConfig = Field(default_factory=PublishingConfig)
    publisher: PublisherConfig = Field(default_factory=PublisherConfig)
    tistory: TistoryBrowserConfig = Field(default_factory=TistoryBrowserConfig)
    stocks_universe: list[SourceItemConfig] = Field(default_factory=list)
    sources_raw: dict[str, Any] = Field(default_factory=dict)
    event_rules: dict[str, Any] = Field(default_factory=dict)

    def resolve(self) -> "Settings":
        """환경 변수로 settings.yaml 의 일부 필드를 오버라이드. 실제 경로를 절대 경로로 확정."""
        env = os.environ

        if env.get("MOCK_MODE"):
            self.app.mock_mode = env["MOCK_MODE"].lower()
        if env.get("AI_PROVIDER"):
            self.ai.provider = env["AI_PROVIDER"].lower()
        if env.get("AI_MODEL"):
            self.ai.model = env["AI_MODEL"]
        if env.get("STOCK_PROVIDER"):
            self.sources_raw.setdefault("stocks", {}).setdefault("price", {})["provider"] = env["STOCK_PROVIDER"]
        if env.get("NEWS_PROVIDER"):
            self.sources_raw.setdefault("news", {})["provider"] = env["NEWS_PROVIDER"]
        if env.get("PUBLISH_BACKEND"):
            self.publishing.backend = env["PUBLISH_BACKEND"]
        if env.get("LOG_LEVEL"):
            self.app.log_level = env["LOG_LEVEL"].upper()
        if env.get("TISTORY_BLOG_URL"):
            self.tistory.blog_url = env["TISTORY_BLOG_URL"]
        if env.get("TISTORY_EDITOR_URL"):
            self.tistory.editor_url = env["TISTORY_EDITOR_URL"]
        if env.get("TISTORY_STORAGE_STATE_PATH"):
            self.tistory.storage_state_path = env["TISTORY_STORAGE_STATE_PATH"]
        if env.get("TISTORY_DRY_RUN"):
            self.tistory.dry_run = env["TISTORY_DRY_RUN"].lower() in ("1", "true", "yes")
        if env.get("TISTORY_VISIBILITY"):
            self.tistory.default_visibility = env["TISTORY_VISIBILITY"]
        if env.get("TISTORY_HEADLESS"):
            self.tistory.headless = env["TISTORY_HEADLESS"].lower() not in ("0", "false", "no")

        def _abs(p: str) -> str:
            path = Path(p)
            return str(path if path.is_absolute() else PROJECT_ROOT / path)

        self.storage.base_dir = _abs(self.storage.base_dir)
        self.content.output_dir = _abs(self.content.output_dir)
        self.charts.output_dir = _abs(self.charts.output_dir)
        self.publishing.content_dir = _abs(self.publishing.content_dir)
        self.tistory.storage_state_path = _abs(self.tistory.storage_state_path)
        return self

    @property
    def effective_backend(self) -> str:
        """발행 백엔드 결정 순서: PUBLISH_BACKEND env > mock 모드 > publisher.type > publishing.backend."""
        backend = os.environ.get("PUBLISH_BACKEND", "").strip().lower()
        if backend:
            return backend
        if str(self.app.mock_mode).lower() == "true":
            return "mock"
        return (self.publisher.type or self.publishing.backend or "local").strip().lower()

    def enabled(self, flag_name: str) -> bool:
        return bool(self.sources_raw.get(flag_name, {}).get("enabled", False))


def load_settings(config_dir: Path | str | None = None) -> Settings:
    """config 디렉토리의 설정을 로드한다. 환경 변수(.env)를 먼저 로드한다."""
    load_dotenv(PROJECT_ROOT / ".env")

    config_dir = Path(config_dir) if config_dir else DEFAULT_CONFIG_DIR

    settings_yaml: dict[str, Any] = {}
    if (config_dir / "settings.yaml").exists():
        with open(config_dir / "settings.yaml", encoding="utf-8") as f:
            settings_yaml = yaml.safe_load(f) or {}

    sources_yaml: dict[str, Any] = {}
    if (config_dir / "sources.yaml").exists():
        with open(config_dir / "sources.yaml", encoding="utf-8") as f:
            sources_yaml = yaml.safe_load(f) or {}

    event_rules: dict[str, Any] = {}
    if (config_dir / "event_rules.yaml").exists():
        with open(config_dir / "event_rules.yaml", encoding="utf-8") as f:
            event_rules = yaml.safe_load(f) or {}

    stocks_universe: list[SourceItemConfig] = []
    stock_sources = sources_yaml.get("stocks", {}).get("universe", []) or []
    for item in stock_sources:
        stocks_universe.append(SourceItemConfig(code=_normalize_code(item["code"]), name=str(item["name"])))

    settings = Settings.model_validate(_interpolate_env(settings_yaml))
    settings.stocks_universe = stocks_universe
    settings.sources_raw = sources_yaml
    settings.event_rules = event_rules
    return settings.resolve()


def _normalize_code(value: Any) -> str:
    """YAML 이 '000660' 를 8진수(432)로 읽는 문제를 방지. 6자리 0 패딩."""
    if isinstance(value, int):
        if value == 0:
            return "000000"
        return str(value).zfill(6)
    s = str(value).strip()
    if s.isdigit() and len(s) < 6:
        return s.zfill(6)
    return s


def _interpolate_env(node: Any) -> Any:
    """딕트/리스트/문자열을 순회하며 '${VAR}' 형태를 환경 변수 값으로 치환한다."""
    import re

    pat = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")

    def repl(s: str) -> str:
        if not s or "${" not in s:
            return s

        def _sub(m: re.Match) -> str:
            key = m.group(1)
            if key in os.environ:
                return os.environ[key]
            return m.group(0)

        return pat.sub(_sub, s)

    if isinstance(node, str):
        return repl(node)
    if isinstance(node, list):
        return [_interpolate_env(v) for v in node]
    if isinstance(node, dict):
        return {k: _interpolate_env(v) for k, v in node.items()}
    return node