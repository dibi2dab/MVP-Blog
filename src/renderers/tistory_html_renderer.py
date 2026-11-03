from __future__ import annotations

import os
import re

from src.models.article import Article
from src.utils.logging import get_logger

logger = get_logger(__name__)

_IMG_SRC_PATTERN = re.compile(r'src="(?P<quote>["\'])?(?P<url>[^"\']+)(?(quote)(?P=quote)|)"')


class TistoryHtmlRenderer:
    """Markdown -> 티스토리 호환 HTML 변환.

    표, 인용문, 코드 블록, 이미지가 깨지지 않도록 마크다운 파이프라인을 고정한다.
    로컬 차트 이미지는 업로드 후 URL 매핑(image_map)으로 치환한다.
    """

    _EXTENSIONS = [
        "markdown.extensions.tables",
        "markdown.extensions.fenced_code",
        "markdown.extensions.sane_lists",
        "markdown.extensions.attr_list",
    ]

    def __init__(self) -> None:
        import markdown as _md

        self._converter = _md.Markdown(extensions=self._EXTENSIONS, output_format="html5")

    def render_markdown(self, markdown_text: str) -> str:
        if not markdown_text:
            return ""
        self._converter.reset()
        html = self._converter.convert(markdown_text)
        return html

    def render(
        self,
        markdown_text: str,
        image_map: dict[str, str] | None = None,
    ) -> str:
        """Markdown -> HTML. image_map: {출력파일명: 업로드URL}."""
        html = self.render_markdown(markdown_text)
        return self.resolve_local_images(html, image_map or {})

    def render_article(self, article: Article, image_map: dict[str, str] | None = None) -> str:
        return self.render(article.body_markdown or "", image_map)

    @staticmethod
    def resolve_local_images(html: str, image_map: dict[str, str]) -> str:
        def _sub(m: re.Match) -> str:
            url = m.group("url")
            base = os.path.basename(url.split("?")[0])
            if base in image_map:
                return f'src="{image_map[base]}"'
            return m.group(0)

        return _IMG_SRC_PATTERN.sub(_sub, html)

    @staticmethod
    def image_basenames(markdown_text: str) -> list[str]:
        """본문에 참조된 로컬 이미지 파일명 목록 (charts/foo.png 등)."""
        names: list[str] = []
        for m in re.finditer(r"!\[[^\]]*\]\(\s*([^)\s]+)\s*\)", markdown_text):
            base = os.path.basename(m.group(1).split("?")[0])
            if base and base not in names:
                names.append(base)
        return names