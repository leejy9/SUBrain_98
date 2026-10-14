"""
Subrain_98 전용 브라우저 세션 관리자 (Browser Session Manager)
==============================================================
- INV-B1: 독립 샌드박스 프로필 (~/.subrain_browser_profile) 보장
  메인 크롬과 완전히 분리되어 'Profile in use' 잠금 충돌 0%
- 1회성 간편 로그인 도구 (--setup) 제공
"""

import sys
import os
import logging
from pathlib import Path
from typing import Optional
from contextlib import contextmanager

try:
    from playwright.sync_api import sync_playwright, BrowserContext
except ImportError:
    sync_playwright = None
    BrowserContext = None

logger = logging.getLogger("browser_session_manager")

PROFILE_DIR = Path.home() / ".subrain_browser_profile"


def ensure_profile_dir() -> Path:
    """전용 프로필 디렉터리가 없으면 생성합니다."""
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    return PROFILE_DIR


def run_setup_interactive(target_url: str = "https://www.instagram.com/"):
    """
    사용자가 수집 전용 부계정으로 1회 로그인할 수 있는 창을 띄웁니다.
    로그인 세션(쿠키, 스토리지)은 ~/.subrain_browser_profile 에 영구 저장됩니다.
    """
    if not sync_playwright:
        print("❌ Playwright가 설치되지 않았습니다. (uv pip install playwright)")
        return

    profile_path = ensure_profile_dir()
    print("\n" + "=" * 60)
    print("🔑 [Subrain_98 전용 크롤러 브라우저 설정]")
    print(f"📁 프로필 저장 경로: {profile_path}")
    print("🌐 브라우저 창이 열립니다. 수집용 부계정으로 로그인해 주세요.")
    print("👉 로그인이 완료되면 브라우저 창을 직접 닫으시면 세션이 영구 저장됩니다.")
    print("=" * 60 + "\n")

    with sync_playwright() as p:
        try:
            # 맥OS 시스템 Google Chrome 바이너리로 독립 세션 기동
            context = p.chromium.launch_persistent_context(
                user_data_dir=str(profile_path),
                channel="chrome",
                headless=False,
                viewport={"width": 1280, "height": 900},
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-first-run",
                    "--no-default-browser-check",
                ],
            )
            page = context.new_page()
            page.goto(target_url, wait_until="commit")

            print("⏳ 브라우저 창이 닫힐 때까지 대기합니다...")
            # 창이 닫힐 때까지 대기
            page.wait_for_event("close", timeout=0)
            context.close()
            print("\n✅ 세션 저장이 완료되었습니다! 이제 백그라운드에서 자동 수집이 가능합니다.\n")
        except Exception as e:
            if "Target page, context or browser has been closed" in str(e):
                print("\n✅ 브라우저가 정상 종료되어 세션이 안전하게 저장되었습니다.\n")
            else:
                logger.error(f"Setup browser error: {e}")
                print(f"\n⚠️ 알림: {e}\n")


@contextmanager
def get_authenticated_page(headless: bool = True):
    """
    수집 전용 부계정 프로필을 장착한 브라우저 페이지를 제공하는 컨텍스트 매니저.
    사용 후 브라우저가 100% 자동 종료되어 메모리를 낭비하지 않습니다. (INV-B2)
    """
    if not sync_playwright:
        raise RuntimeError("Playwright is not available")

    profile_path = ensure_profile_dir()
    with sync_playwright() as p:
        context = None
        try:
            context = p.chromium.launch_persistent_context(
                user_data_dir=str(profile_path),
                channel="chrome",
                headless=headless,
                viewport={"width": 1280, "height": 900},
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-first-run",
                    "--no-default-browser-check",
                ],
            )
            page = context.new_page()
            yield page
        finally:
            if context:
                try:
                    context.close()
                except Exception:
                    pass


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Subrain 브라우저 세션 관리자")
    parser.add_argument("--setup", action="store_true", help="수집용 부계정 1회 로그인 창 실행")
    parser.add_argument("--url", default="https://www.instagram.com/", help="초기 오픈 주소")
    args = parser.parse_args()

    if args.setup:
        run_setup_interactive(args.url)
    else:
        print("사용법: python daemon/browser_session_manager.py --setup")
