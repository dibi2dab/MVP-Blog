from __future__ import annotations

from pydantic import BaseModel, Field

from src.models.analysis import AnalysisReport
from src.models.event import Event
from src.models.source import utc_now_iso


class ArticleSection(BaseModel):
    heading: str
    body: str = ""


class ArticleImage(BaseModel):
    """Article 생성 단계에서 사용하는 로컬 이미지 메타데이터. 최종 URL은 아니다.

    - local_path: 디스크 상의 원본 파일 (예: static/charts/...)
    - alt: 이미지 대체 텍스트
    - position: 본문 내 배치 위치 키 (예: price_analysis, volume_analysis, overview)
    TistoryPublisher가 업로드 후 이 항목에 티스토리 URL을 채운다.
    """

    local_path: str = ""
    alt: str = ""
    position: str = ""
    remote_url: str = ""  # 발행 단계에서 채워짐


class Article(BaseModel):
    """최종 블로그 글 (Markdown 생성 전 단계)."""

    article_id: str
    event: Event
    title: str
    slug: str
    description: str = ""
    category: str = "stocks"
    tags: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    sections: list[ArticleSection] = Field(default_factory=list)
    images: list[ArticleImage] = Field(default_factory=list)
    analysis_report: AnalysisReport | None = None
    chart_paths: list[str] = Field(default_factory=list)
    external_chart_embeds: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=utc_now_iso)
    status: str = "draft"
    content_hash: str = Field(default="")
    frontmatter: dict = Field(default_factory=dict)
    body_markdown: str = ""
    published_at: str | None = None
    published_url: str | None = None
    publish_backend: str | None = None
    published_message: str = ""
    published_visibility: str = ""

    # 자체 계산 지표와 발행 준비 상태. 내부 점수·가중치는 공개 본문에 쓰지 않는다.
    visibility: str = "private"
    quality_score: float = 0.0
    public_ready: bool = False
    data_metrics: dict[str, float] = Field(default_factory=dict)
    review_notes: list[str] = Field(default_factory=list)
    readiness: dict = Field(default_factory=dict)

    @property
    def full_markdown(self) -> str:
        parts: list[str] = []
        fm = dict(self.frontmatter)
        fm["published_at"] = self.published_at or self.created_at
        import json

        parts.append("---")
        parts.append(json.dumps(fm, ensure_ascii=False, indent=2))
        parts.append("---")
        parts.append("")
        parts.append(self.body_markdown or "")
        return "\n".join(parts)


class ArticleToPublish(BaseModel):
    article: Article
    backend: str = "tistory"
    images: list[str] = Field(default_factory=list)