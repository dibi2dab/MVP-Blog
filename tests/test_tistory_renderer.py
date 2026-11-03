from __future__ import annotations

from src.renderers.tistory_html_renderer import TistoryHtmlRenderer

MD = """# 제목

## 오늘의 주가

본문 문단입니다. **강조**와 *기울임*을 지원한다.

- 목록 1
- 목록 2

> 인용문입니다.

| 항목 | 값 |
| --- | --- |
| 종가 | 10000 |

```python
print("hello")
```

[링크](https://example.com) ![차트](../static/charts/abc.png)
"""


def test_headings_and_structure():
    html = TistoryHtmlRenderer().render_markdown(MD)
    assert "<h1" in html and "제목" in html
    assert "<h2" in html and "오늘의 주가" in html


def test_inline_and_lists():
    html = TistoryHtmlRenderer().render_markdown(MD)
    assert "<strong>강조</strong>" in html
    assert "<em>기울임</em>" in html
    assert "<ul>" in html


def test_table_rendered():
    html = TistoryHtmlRenderer().render_markdown(MD)
    assert "<table>" in html
    assert "<th>항목</th>" in html


def test_blockquote_and_code():
    html = TistoryHtmlRenderer().render_markdown(MD)
    assert "<blockquote>" in html
    assert "<code" in html


def test_local_image_replaced_by_upload_url():
    image_map = {"abc.png": "https://files.tistory.com/upload/abc.png"}
    html = TistoryHtmlRenderer().render(MD, image_map=image_map)
    assert 'src="https://files.tistory.com/upload/abc.png"' in html
    assert "static/charts" not in html


def test_missing_image_map_keeps_src():
    html = TistoryHtmlRenderer().render_markdown(MD)
    assert "assets/images/abc.png" not in html  # 컨텐츠 보존 확인


def test_image_basenames():
    names = TistoryHtmlRenderer.image_basenames(MD)
    assert "abc.png" in names


def test_empty_input():
    assert TistoryHtmlRenderer().render_markdown("") == ""