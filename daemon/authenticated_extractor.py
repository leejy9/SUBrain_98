"""
Subrain_98 인증 기반 브라우저 & 인스타그램 카드뉴스 추출기
=============================================================
- INV-B1: 전용 프로필 (~/.subrain_browser_profile) 독립 구동
- INV-B2: 인스타/차단 사이트 인입 시에만 온디맨드 백그라운드 기동 후 즉시 종료
- INV-B3: 카드뉴스 슬라이드 이미지 수집 ➔ Gemini Vision 멀티모달 OCR 마크다운 복원
- INV-B4: 세션 만료 감지 시 정직한 터미널 1회 재로그인 안내
"""

import re
import logging
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any
import httpx
from google import genai
from google.genai import types

from daemon.config import GEMINI_API_KEY
from daemon.browser_session_manager import get_authenticated_page

logger = logging.getLogger("authenticated_extractor")


@dataclass
class AuthenticatedContent:
    source_type: str        # 'instagram', 'authenticated_web'
    url: str
    title: str
    content: str
    images_count: int = 0
    is_session_expired: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)


class AuthenticatedExtractor:
    def __init__(self):
        self.gemini_client = genai.Client(api_key=GEMINI_API_KEY)
        self.vision_model = "gemini-3.1-flash-lite"  # 고속 멀티모달 비전 모델

    def is_target(self, url: str) -> bool:
        """인증 브라우저 기동 대상인지 검사합니다."""
        u = url.lower()
        return "instagram.com" in u or "instagr.am" in u

    def extract_instagram(self, url: str) -> AuthenticatedContent:
        """
        인스타그램 링크에서 백그라운드 브라우저로 슬라이드 이미지를 수집하고,
        Gemini Vision으로 카드뉴스 텍스트를 순차 복원합니다. (INV-B2, INV-B3)
        """
        # 첫 슬라이드부터 시작하기 위해 ?img_index 등 쿼리스트링 제거
        clean_url = re.sub(r"\?.*$", "", url)
        logger.info(f"[AuthenticatedExtractor] 인스타그램 수집 시작: {clean_url} (원본: {url})")
        slide_image_urls: List[str] = []
        caption_text = ""
        author = "Instagram"
        is_expired = False

        try:
            with get_authenticated_page(headless=True) as page:
                page.goto(clean_url, wait_until="domcontentloaded", timeout=15000)
                page.wait_for_timeout(3000)  # JS 렌더링 안정화 3초 대기

                current_url = page.url
                # 세션 만료 검사 (INV-B4)
                if "accounts/login" in current_url:
                    logger.warning("[AuthenticatedExtractor] 인스타그램 세션 만료/로그인 필요 감지")
                    return AuthenticatedContent(
                        source_type="instagram",
                        url=url,
                        title="인스타그램 로그인 필요",
                        content=(
                            "🔑 [인스타그램 전용 프로필 로그인 필요]\n"
                            "수집 전용 부계정의 로그인이 만료되었거나 처음 설정이 필요합니다.\n"
                            "맥북 터미널에서 아래 명령어를 1회 실행하여 로그인해 주세요:\n\n"
                            "`python daemon/browser_session_manager.py --setup`"
                        ),
                        is_session_expired=True,
                    )

                # 1. og 메타데이터 우선 추출
                try:
                    og_title = page.evaluate("() => document.querySelector(\"meta[property='og:title']\")?.content || \"\"")
                    og_desc = page.evaluate("() => document.querySelector(\"meta[property='og:description']\")?.content || \"\"")
                except Exception:
                    og_title = ""
                    og_desc = ""

                # 2. 작성자 추출 (본문 텍스트 패턴 -> og:title -> 헤더 태그)
                try:
                    body_text = page.inner_text("body")
                    author_match = re.search(r"([a-zA-Z0-9._]+)님의 게시물", body_text)
                    if author_match:
                        author = author_match.group(1).strip()
                    elif og_title and "의" in og_title:
                        author = og_title.split("의")[0].replace("Instagram", "").strip()
                    else:
                        title_elem = page.query_selector("header h2, header a, a[role='link'][tabindex='0'] span")
                        if title_elem:
                            author = title_elem.inner_text().strip()
                except Exception as e:
                    logger.debug(f"[AuthenticatedExtractor] 작성자 추출 보조 실패: {e}")

                # 3. 캡션 텍스트 추출 (og:description -> og:title -> span)
                try:
                    if og_desc and ":" in og_desc:
                        caption_text = og_desc.split(":", 1)[1].strip().strip('"').strip()
                    elif og_title and ":" in og_title:
                        caption_text = og_title.split(":", 1)[1].strip().strip('"').strip()
                    
                    if not caption_text:
                        spans = page.query_selector_all("main span, div span")
                        for s in spans:
                            t = s.inner_text().strip()
                            if len(t) > len(caption_text) and "로그인" not in t and "이용 약관" not in t:
                                caption_text = t
                except Exception as e:
                    logger.debug(f"[AuthenticatedExtractor] 캡션 추출 보조 실패: {e}")

                # 4. 카드뉴스 슬라이드 이미지 수집 (캐러셀 넘기기)
                collected_srcs = set()
                for step in range(12):  # 최대 12장 슬라이드 탐색
                    imgs = page.query_selector_all("main img, img")
                    for img in imgs:
                        src = img.get_attribute("src")
                        if not src or "cdninstagram.com" not in src or src in collected_srcs:
                            continue
                        box = img.bounding_box()
                        if not box:
                            continue
                        # 본문 카드뉴스 이미지 필터링 (가로세로 300px 이상, 상단 뷰포트 내)
                        if box["width"] >= 280 and box["height"] >= 280 and box["y"] < 750:
                            collected_srcs.add(src)
                            slide_image_urls.append(src)

                    # '다음' 슬라이드 화살표 버튼 탐색 및 자바스크립트 강제 클릭 (모달 오버레이 회피)
                    next_btn = page.query_selector(
                        "button[aria-label*='다음'], button[aria-label*='Next'], button[aria-label*='next']"
                    )
                    if next_btn:
                        try:
                            page.evaluate("el => el.click()", next_btn)
                            page.wait_for_timeout(800)  # 슬라이드 전환 대기
                        except Exception:
                            break
                    else:
                        break

        except Exception as e:
            logger.error(f"[AuthenticatedExtractor] 브라우저 수집 오류: {e}")

        logger.info(f"[AuthenticatedExtractor] 슬라이드 이미지 {len(slide_image_urls)}장 확보, 캡션 {len(caption_text)}자")

        # Gemini Vision OCR로 카드뉴스 텍스트 복원 (INV-B3)
        ocr_result_markdown = ""
        if slide_image_urls:
            ocr_result_markdown = self._transcribe_slides_with_vision(slide_image_urls[:10])

        final_title = f"{author} 인스타 카드뉴스: {caption_text[:25].replace(chr(10), ' ')}"
        if not caption_text and not ocr_result_markdown:
            final_content = f"[인스타그램 포스트: {url}]\n작성자: {author}\n(본문 추출 실패 또는 비공개 계정)"
        else:
            final_content = (
                f"[인스타그램 출처: {url}]\n"
                f"[계정: {author}]\n\n"
                f"### 📝 작성자 캡션\n{caption_text or '(캡션 없음)'}\n\n"
                f"### 🖼️ 카드뉴스 슬라이드 복원 본문 (Gemini OCR)\n"
                f"{ocr_result_markdown or '(이미지 텍스트 없음)'}"
            )

        return AuthenticatedContent(
            source_type="instagram",
            url=url,
            title=final_title,
            content=final_content,
            images_count=len(slide_image_urls),
            metadata={"author": author, "slides": len(slide_image_urls)}
        )

    def _transcribe_slides_with_vision(self, image_urls: List[str]) -> str:
        """슬라이드 이미지들을 다운로드하여 Gemini Vision에 일괄 전달 후 마크다운으로 복원"""
        import time
        parts = []
        with httpx.Client(timeout=10.0) as client:
            for idx, img_url in enumerate(image_urls, start=1):
                try:
                    resp = client.get(img_url)
                    if resp.status_code == 200:
                        parts.append(types.Part.from_bytes(data=resp.content, mime_type="image/jpeg"))
                except Exception as e:
                    logger.warning(f"이미지 {idx} 다운로드 실패: {e}")

        if not parts:
            return ""

        prompt = (
            "당신은 인스타그램 카드뉴스 지식 복원 전문가입니다.\n"
            "첨부된 이미지들은 순서대로 나열된 카드뉴스 슬라이드(1번부터 끝번까지)입니다.\n"
            "각 슬라이드의 헤드라인, 핵심 설명, 수치/통계, 강조 문구를 순서대로 누락 없이 마크다운으로 정리해 주세요.\n"
            "형식:\n"
            "#### [슬라이드 1] 제목/헤드라인\n"
            "- 내용 요약 및 텍스트 전문\n\n"
            "불필요한 인사말 없이 마크다운 본문만 출력하세요."
        )
        parts.append(prompt)

        candidate_models = [self.vision_model, "gemini-3.8-flash", "gemini-3.5-flash", "gemini-flash-latest"]
        for model_name in candidate_models:
            for attempt in range(2):
                try:
                    logger.info(f"[AuthenticatedExtractor] Vision OCR 요청 ({model_name}, 시도 {attempt+1})")
                    response = self.gemini_client.models.generate_content(
                        model=model_name,
                        contents=parts,
                    )
                    if response.text and response.text.strip():
                        return response.text.strip()
                except Exception as e:
                    logger.warning(f"[AuthenticatedExtractor] {model_name} (시도 {attempt+1}) 실패: {e}")
                    time.sleep(1.5)
            logger.info(f"[AuthenticatedExtractor] {model_name} 실패로 다음 후보 모델로 폴백")

        logger.error("[AuthenticatedExtractor] 모든 Vision 모델 OCR 복원 실패")
        return ""



authenticated_extractor = AuthenticatedExtractor()

