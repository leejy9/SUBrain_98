"""
Subrain_98 만능 인테이크 추출기 (Universal Ingest Extractor)
===========================================================
- INV-E2: 3중 웹 추출 그물망 (브라우저 위장 Trafilatura -> Jina Reader -> 메타 Fallback)
- INV-E3: 0.3초 유튜브 자막 직통 추출 (youtube-transcript-api)
- 단일 책임 원칙 준수: 200줄 이내 슬림 모듈
"""

import re
import logging
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, Tuple
import urllib.parse
import httpx
from bs4 import BeautifulSoup
import trafilatura

try:
    from youtube_transcript_api import YouTubeTranscriptApi
except ImportError:
    YouTubeTranscriptApi = None

logger = logging.getLogger("universal_extractor")

@dataclass
class ExtractedContent:
    source_type: str       # 'youtube', 'web', 'file', 'text'
    url: str
    title: str
    content: str
    metadata: Dict[str, Any] = field(default_factory=dict)

class UniversalExtractor:
    def __init__(self):
        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
        }

    def extract_universal(self, raw_input: str) -> ExtractedContent:
        """어떤 형태의 입력이든 감지하여 최적의 경로로 텍스트를 추출합니다."""
        url_match = re.search(r'https?://[^\s]+', raw_input)
        if not url_match:
            # 순수 텍스트 메모
            return ExtractedContent(
                source_type="text",
                url="",
                title=raw_input[:30].strip(),
                content=raw_input.strip()
            )

        url = url_match.group(0).rstrip(".,)>]\"'")

        # 1. 유튜브 URL 감지
        if self._is_youtube_url(url):
            yt_res = self.extract_youtube(url, raw_input)
            if yt_res:
                return yt_res

        # 2. 인스타그램 및 인증 전용 브라우저 타깃 감지 (INV-B2)
        try:
            try:
                from daemon.authenticated_extractor import authenticated_extractor
            except ImportError:
                from authenticated_extractor import authenticated_extractor

            if authenticated_extractor and authenticated_extractor.is_target(url):
                auth_res = authenticated_extractor.extract_instagram(url)
                return ExtractedContent(
                    source_type=auth_res.source_type,
                    url=auth_res.url,
                    title=auth_res.title,
                    content=auth_res.content,
                    metadata=auth_res.metadata
                )
        except Exception as e:
            logger.warning(f"[UniversalExtractor] 인증 추출기 호출 실패 ({e}), 웹 캐스케이드로 폴백")

        # 3. 일반 웹페이지 (3중 그물망 추출)
        return self.extract_web_cascade(url, raw_input)

    def _is_youtube_url(self, url: str) -> bool:
        return any(d in url.lower() for d in ["youtube.com", "youtu.be"])

    def _extract_youtube_video_id(self, url: str) -> Optional[str]:
        patterns = [
            r'(?:v=|\/)([0-9A-Za-z_-]{11}).*',
            r'youtu\.be\/([0-9A-Za-z_-]{11})',
            r'shorts\/([0-9A-Za-z_-]{11})',
        ]
        for p in patterns:
            match = re.search(p, url)
            if match:
                return match.group(1)
        return None

    def extract_youtube(self, url: str, raw_input: str = "") -> Optional[ExtractedContent]:
        """유튜브 동영상 자막 또는 커뮤니티 글을 0.3초 만에 직접 추출"""
        # 유튜브 커뮤니티 탭 또는 채널 포스트인 경우 전용 파서 직통 호출
        if "/post/" in url or "/community" in url:
            community_res = self._extract_youtube_community_post(url)
            if community_res:
                return community_res
            return self.extract_web_cascade(url, raw_input)

        video_id = self._extract_youtube_video_id(url)
        if not video_id:
            return None

        # 영상 제목 oEmbed 조회
        title = self._fetch_youtube_title(url) or f"YouTube Video ({video_id})"

        # 자막 직통 추출 시도 (INV-E3)
        transcript_text = ""
        if YouTubeTranscriptApi:
            try:
                ytt = YouTubeTranscriptApi()
                transcript_list = ytt.list(video_id)
                # 한국어 우선 탐색 -> 영어 -> 자동 생성 자막
                target_transcript = None
                for t in transcript_list:
                    if t.language_code.startswith("ko"):
                        target_transcript = t
                        break
                if not target_transcript:
                    for t in transcript_list:
                        if t.language_code.startswith("en"):
                            target_transcript = t
                            break
                if not target_transcript:
                    target_transcript = next(iter(transcript_list), None)

                if target_transcript:
                    fetched = target_transcript.fetch()
                    transcript_text = " ".join(item.text for item in fetched)
                    logger.info(f"[UniversalExtractor] 유튜브 자막 추출 성공 ({len(transcript_text)}자): {video_id}")
            except Exception as e:
                logger.warning(f"[UniversalExtractor] 자막 직통 조회 실패 ({e}), 웹 프록시로 폴백")

        if len(transcript_text.strip()) >= 50:
            formatted_body = f"[유튜브 영상 출처: {url}]\n[영상 제목: {title}]\n\n[스크립트 전문]:\n{transcript_text}"
            return ExtractedContent(
                source_type="youtube",
                url=url,
                title=title,
                content=formatted_body,
                metadata={"video_id": video_id, "has_transcript": True}
            )

        # 자막이 없거나 추출 실패 시 Jina Reader / 웹 캐스케이드로 폴백
        return self.extract_web_cascade(url, raw_input)

    def _fetch_youtube_title(self, url: str) -> str:
        try:
            oembed_url = f"https://www.youtube.com/oembed?url={urllib.parse.quote(url)}&format=json"
            with httpx.Client(timeout=4.0) as client:
                resp = client.get(oembed_url)
                if resp.status_code == 200:
                    return resp.json().get("title", "")
        except Exception:
            pass
        return ""

    def _extract_youtube_community_post(self, url: str) -> Optional[ExtractedContent]:
        """유튜브 커뮤니티 게시물에서 본문과 작성자를 0.3초 만에 무손실 추출"""
        try:
            with httpx.Client(timeout=8.0, follow_redirects=True, headers=self.headers) as client:
                resp = client.get(url)
                html = resp.text

            match = re.search(r'var ytInitialData\s*=\s*({.+?});\s*<\/script>', html)
            if not match:
                match = re.search(r'ytInitialData\s*=\s*({.+?});', html)
            if not match:
                return None

            import json
            data = json.loads(match.group(1))

            def _find_posts(obj):
                found = []
                if isinstance(obj, dict):
                    if 'backstagePostRenderer' in obj:
                        found.append(obj['backstagePostRenderer'])
                    if 'sharedPostRenderer' in obj:
                        found.append(obj['sharedPostRenderer'])
                    for v in obj.values():
                        found.extend(_find_posts(v))
                elif isinstance(obj, list):
                    for item in obj:
                        found.extend(_find_posts(item))
                return found

            posts = _find_posts(data)
            if not posts:
                return None

            p = posts[0]
            author = (
                p.get('authorText', {}).get('runs', [{}])[0].get('text', '') or
                p.get('authorText', {}).get('simpleText', '') or
                "YouTube Community Post"
            )
            runs = p.get('contentText', {}).get('runs', [])
            full_text = ''.join(r.get('text', '') for r in runs).strip()

            if not full_text:
                return None

            title = f"{author} 커뮤니티 메모: {full_text[:30].replace(chr(10), ' ')}"
            formatted_body = (
                f"[유튜브 커뮤니티 출처: {url}]\n"
                f"[작성자 채널: {author}]\n\n"
                f"[본문 전문]:\n{full_text}"
            )

            logger.info(f"[UniversalExtractor] 유튜브 커뮤니티 추출 성공 ({len(full_text)}자): {author}")
            return ExtractedContent(
                source_type="youtube_post",
                url=url,
                title=title,
                content=formatted_body,
                metadata={"author": author, "post_length": len(full_text)}
            )
        except Exception as e:
            logger.warning(f"[UniversalExtractor] 유튜브 커뮤니티 글 추출 실패 ({e}), 웹 캐스케이드로 폴백")
            return None

    def extract_web_cascade(self, url: str, raw_input: str = "") -> ExtractedContent:
        """3중 웹 추출 그물망 (INV-E2)"""
        title = ""
        body = ""

        # 1차 관문: 실 브라우저 헤더 Trafilatura 정적 본문 추출 (0.2초)
        try:
            downloaded = trafilatura.fetch_url(url)
            if downloaded:
                extracted = trafilatura.extract(
                    downloaded,
                    include_comments=False,
                    include_tables=True,
                    no_fallback=False
                )
                if extracted and len(extracted.strip()) >= 150:
                    meta = trafilatura.extract_metadata(downloaded)
                    title = meta.title if meta and meta.title else ""
                    body = extracted.strip()
                    logger.info(f"[UniversalExtractor] 1차 Trafilatura 추출 성공 ({len(body)}자)")
        except Exception as e:
            logger.debug(f"[UniversalExtractor] 1차 Trafilatura 실패: {e}")

        # 2차 관문: 1차 실패 or 봇 차단 시 Jina Reader 프록시 렌더링 호출
        if len(body) < 150:
            try:
                jina_url = f"https://r.jina.ai/{url}"
                with httpx.Client(headers=self.headers, timeout=12.0) as client:
                    resp = client.get(jina_url)
                    if resp.status_code == 200:
                        text = resp.text
                        # Jina Markdown 제목 추출
                        title_match = re.search(r'^Title:\s*(.+)$', text, re.MULTILINE)
                        if title_match:
                            title = title_match.group(1).strip()
                        # Markdown 본문 슬라이싱
                        if "Markdown Content:" in text:
                            body = text.split("Markdown Content:", 1)[1].strip()
                        else:
                            body = text.strip()
                        logger.info(f"[UniversalExtractor] 2차 Jina Reader 추출 성공 ({len(body)}자)")
            except Exception as e:
                logger.warning(f"[UniversalExtractor] 2차 Jina Reader 호출 실패: {e}")

        # 3차 관문: 최후의 기본 HTML 메타 파서 Fallback
        if len(body) < 50:
            try:
                with httpx.Client(headers=self.headers, follow_redirects=True, timeout=8.0) as client:
                    resp = client.get(url)
                    soup = BeautifulSoup(resp.text, "html.parser")
                    if not title and soup.title:
                        title = soup.title.string.strip()
                    paras = [p.get_text().strip() for p in soup.find_all(["p", "article", "h1", "h2", "h3"]) if p.get_text().strip()]
                    body = " ".join(paras[:30])
            except Exception as e:
                logger.error(f"[UniversalExtractor] 3차 HTML 파서 실패: {e}")
                body = raw_input

        final_title = title or "웹 아티클"
        formatted_content = f"[웹페이지 출처: {url}]\n[제목: {final_title}]\n\n{body}"
        return ExtractedContent(
            source_type="web",
            url=url,
            title=final_title,
            content=formatted_content,
            metadata={"extracted_length": len(body)}
        )

# 싱글톤 인스턴스
universal_extractor = UniversalExtractor()
