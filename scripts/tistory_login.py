from __future__ import annotations

"""최초 1회 티스토리 로그인 세션 생성 스크립트.

사용법:
    python scripts/tistory_login.py
    python scripts/tistory_login.py --state-out .state/tistory_storage_state.json
    python scripts/tistory_login.py --base64-out .state/tistory_storage_state.b64

브라우저가 열리면 사용자가 직접 카카오 계정으로 로그인한다(2차 인증 포함).
로그인 완료 후 Enter 를 누르면 로그인 세션(쿠키)이 storage_state 파일로 저장되고,
선택 시 Base64 인코딩 파일을 생성해 GitHub Secret(TISTORY_STORAGE_STATE)으로 등록할 수 있다.

주의: 생성된 세션 파일은 민감 정보를 포함한다. 절대 커밋하지 않고, 로그에 출력하지 않는다.
"""

import argparse
import base64
import pathlib
import sys

try:
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover
    print("playwright 가 설치되지 않았습니다. 먼저 `pip install playwright && playwright install chromium` 실행")
    sys.exit(1)

_DEFAULT_OUT = pathlib.Path(".state") / "tistory_storage_state.json"
_LOGIN_URL = "https://www.tistory.com/auth/login?redirectUrl=https%3A%2F%2Fwww.tistory.com%2F"
_HOME_URL = "https://www.tistory.com/"


def _is_logged_in(page) -> bool:
    # 로그인 직후 홈으로의 리다이렉트가 진행 중이어서 goto 충돌("interrupted by another
    # navigation")이 날 수 있다. commit 까지만 대기하고 재시도하며 견딘다.
    page.wait_for_timeout(3000)
    for attempt in range(3):
        try:
            page.goto(_HOME_URL, wait_until="commit", timeout=30000)
            page.wait_for_load_state("domcontentloaded", timeout=15000)
            break
        except Exception:
            page.wait_for_timeout(2000)
    el = page.locator("#kakaoGnbProfileImg, a[href*='/manage']").first
    try:
        el.wait_for(state="attached", timeout=5000)
        return True
    except Exception:
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Tistory login session generator")
    parser.add_argument("--state-out", default=str(_DEFAULT_OUT), help="storage state JSON 출력 경로")
    parser.add_argument("--base64-out", default="", help="Base64 인코딩 파일 출력 경로 (GitHub Secret 등록용)")
    parser.add_argument("--headful-timeout", type=int, default=300, help="로그인 대기 최대 시간(초)")
    args = parser.parse_args()

    out = pathlib.Path(args.state_out)
    out.parent.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)
        ctx = browser.new_context()
        page = ctx.new_page()
        page.set_default_timeout(30000)

        page.goto(_LOGIN_URL, wait_until="domcontentloaded")
        print("브라우저가 열렸습니다. 티스토리/카카오 계정으로 직접 로그인하세요. (2차 인증 포함)")
        print("로그인이 끝난 뒤 여기서 Enter 를 누르면 세션이 저장됩니다.")
        try:
            input("Enter <- 로그인 완료 확인 대기...")
        except EOFError:
            pass

        if not _is_logged_in(page):
            print("경고: 로그인 상태가 확인되지 않았습니다. 세션 파일을 생성하지만 발행 시 실패할 수 있습니다.")

        ctx.storage_state(path=str(out))
        print(f"storage state 저장 완료: {out}")

        if args.base64_out:
            encoded = base64.b64encode(out.read_bytes()).decode("ascii")
            b64 = pathlib.Path(args.base64_out)
            b64.parent.mkdir(parents=True, exist_ok=True)
            b64.write_text(encoded, encoding="ascii")
            print(f"Base64 파일 저장 (GitHub Secret 'TISTORY_STORAGE_STATE' 등록용): {b64}")
            print("절대 로그 출력/커밋 금지.")

        browser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())