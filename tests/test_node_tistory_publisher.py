from __future__ import annotations

import subprocess
from types import SimpleNamespace

from src.models.article import Article, ArticleSection
from src.models.event import Event
from src.models.source import EntityRef
from src.publishers import PublisherFactory
from src.publishers.node_tistory_publisher import NodeTistoryPublisher
from src.storage.file_store import JsonStore


def _article() -> Article:
    event = Event(
        event_id="e1",
        event_type="stock_crash",
        entity=EntityRef(name="코미팜", ticker="041960"),
    )
    return Article(
        article_id="a1",
        event=event,
        title="[2026년 9월 2일] 코미팜 5.37% 하락…거래량은 평균의 3.1배",
        slug="komipharm-down",
        sections=[ArticleSection(heading="본문", body="본문입니다. " * 200)],
        sources=["Google News"],
        category="stocks",
        tags=["코미팜", "급락주"],
        body_markdown="## 본문\n\n" + ("본문입니다. " * 200),
    )


def _publisher(settings) -> NodeTistoryPublisher:
    settings.tistory = settings.tistory.model_copy(
        update={
            "blog_url": "https://eneru.tistory.com",
            "category_map": {"stocks": "주식 정보"},
            "dry_run": False,
        }
    )
    settings.content = settings.content.model_copy(
        update={"categories": {"stocks": "주식 정보"}}
    )
    return NodeTistoryPublisher(settings, JsonStore(settings))


def test_factory_builds_node_publisher(settings):
    pub = PublisherFactory(settings, JsonStore(settings)).build("tistory-node")
    assert isinstance(pub, NodeTistoryPublisher)
    assert pub.name == "tistory-node"


def test_build_payload_maps_category_and_images(settings, tmp_path):
    img = tmp_path / "price_volume_abc.png"
    img.write_bytes(b"x")
    pub = _publisher(settings)

    payload = pub._build_payload(
        _article(),
        "![chart](/charts/price_volume_abc.png)",
        [str(img)],
    )

    assert payload["title"].startswith("[2026년 9월 2일]")
    assert payload["tistoryCategory"] == "주식 정보"
    assert payload["blogName"] == "eneru"
    assert payload["visibility"] == settings.tistory.default_visibility
    assert payload["imagePaths"] == [str(img.resolve())]
    assert "/charts/price_volume_abc.png" in payload["contentHtml"]
    assert payload["tags"] == ["코미팜", "급락주"]


def test_build_payload_strips_duplicate_title_heading(settings):
    pub = _publisher(settings)
    article = _article()

    payload = pub._build_payload(article, f"# {article.title}\n\n본문입니다.", [])

    assert not payload["contentHtml"].lstrip().startswith("<h1>")
    assert "본문입니다." in payload["contentHtml"]


def test_build_payload_keeps_different_heading(settings):
    pub = _publisher(settings)
    article = _article()

    payload = pub._build_payload(article, "# 다른 제목\n\n본문입니다.", [])

    assert payload["contentHtml"].lstrip().startswith("<h1>다른 제목</h1>")


def test_run_node_parses_sentinel(settings, monkeypatch):
    pub = _publisher(settings)
    fake = subprocess.CompletedProcess(
        args=[],
        returncode=0,
        stdout='noise\n__PUBLISH_RESULT__{"ok": true, "publishedUrl": "https://eneru.tistory.com/entry/1"}\n',
        stderr="",
    )
    monkeypatch.setattr(
        "src.publishers.node_tistory_publisher.subprocess.run",
        lambda *args, **kwargs: fake,
    )

    result = pub._run_node("node", {"title": "t"})

    assert result["ok"] is True
    assert result["publishedUrl"].endswith("/entry/1")


def test_publish_maps_session_expired(settings, monkeypatch):
    pub = _publisher(settings)
    monkeypatch.setattr(
        "src.publishers.node_tistory_publisher.run_pre_publish_checks",
        lambda *args, **kwargs: SimpleNamespace(ok=True, issues=[]),
    )
    monkeypatch.setattr(
        pub,
        "_run_node",
        lambda *args, **kwargs: {
            "ok": False,
            "error": "redirected to login page",
            "errorCode": "TISTORY_SESSION_EXPIRED",
        },
    )

    result = pub.publish(_article(), "body", [])

    assert result.ok is False
    assert result.error_code == "TISTORY_SESSION_EXPIRED"


def test_publish_dry_run(settings):
    pub = _publisher(settings)
    settings.tistory = settings.tistory.model_copy(update={"dry_run": True})

    result = pub.publish(_article(), _article().body_markdown, [])

    assert result.ok is False
    assert result.error_code == "TISTORY_DRY_RUN"
