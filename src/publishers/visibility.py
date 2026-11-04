from __future__ import annotations

"""발행 공개 범위 정책.

자동 발행의 기본값은 비공개다. `publishing.allow_public=false` 이면
TISTORY_VISIBILITY=public 이 설정돼 있어도 절대 공개하지 않는다.
공개는 readiness.public_ready 까지 통과한 기사에만 허용한다.
"""

from src.config.settings import Settings
from src.models.article import Article

_ALLOWED = {"private", "protected", "public"}


def resolve_visibility(article: Article, settings: Settings, public_ready: bool = False) -> str:
    requested = (settings.tistory.default_visibility or "private").lower()
    if requested not in _ALLOWED:
        requested = "private"

    # 자동 운영 기본 정책: 공개 허용 스위치가 꺼져 있으면 무조건 비공개.
    if not settings.publishing.allow_public:
        return "private"

    if requested == "private":
        return "private"

    # 공개/보호 발행은 준비도·품질·팩트체크를 모두 통과한 기사만.
    if requested in ("public", "protected"):
        return requested if public_ready else "private"

    return "private"
