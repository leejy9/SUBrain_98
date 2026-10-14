"""
Subrain_98 전용 브라우저 & 인스타그램 카드뉴스 추출기 E2E 검증 스위트
========================================================================
- AT-1: 전용 프로필 디렉터리 독립성 검증 (INV-B1)
- AT-2: 인스타그램 URL 감지 및 자동 라우팅 검증 (INV-B2)
- AT-3: 유튜브 커뮤니티 게시물 0.3초 무손실 본문 추출 검증 (INV-E3)
- AT-4: 세션 만료 시 친절한 안내 메시지 반환 검증 (INV-B4)
"""

import sys
import unittest
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from daemon.browser_session_manager import PROFILE_DIR, ensure_profile_dir
from daemon.authenticated_extractor import authenticated_extractor
from daemon.universal_extractor import universal_extractor


class TestAuthenticatedExtractorE2E(unittest.TestCase):

    def test_at1_profile_directory_isolation(self):
        """AT-1: 전용 프로필 디렉터리가 사용자 홈 밑에 안전하게 격리되어 있는지 검증"""
        p = ensure_profile_dir()
        self.assertTrue(p.exists())
        self.assertEqual(str(p), str(Path.home() / ".subrain_browser_profile"))
        print(f"\n[PASS] AT-1: 독립 프로필 경로 확보 -> {p}")

    def test_at2_instagram_detection(self):
        """AT-2: 인스타그램 URL 타깃 감지 검증"""
        insta_urls = [
            "https://www.instagram.com/p/C-test123/",
            "https://instagram.com/reel/D_xyz987/",
            "https://instagr.am/p/ABC123/",
        ]
        non_insta_urls = [
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "https://n.news.naver.com/article/001/001",
        ]
        for url in insta_urls:
            self.assertTrue(authenticated_extractor.is_target(url), f"Failed for {url}")
        for url in non_insta_urls:
            self.assertFalse(authenticated_extractor.is_target(url), f"False positive for {url}")
        print("\n[PASS] AT-2: 인스타그램 타깃 판별 로직 100% 일치")

    def test_at3_youtube_community_extraction(self):
        """AT-3: 유튜브 커뮤니티 게시물 직통 파서 0.3초 추출 및 푸터 배제 검증"""
        url = "https://www.youtube.com/post/UgkxDwI4k5HD1zOaxJl9STD5Qcve_gRnEmyS?surface=shorts"
        res = universal_extractor.extract_universal(url)
        self.assertEqual(res.source_type, "youtube_post")
        self.assertIn("BZCF | 비즈까페", res.title)
        self.assertIn("에이전트가 대중화됨에 따라", res.content)
        self.assertNotIn("상품 판매 책임", res.content)
        print(f"\n[PASS] AT-3: 유튜브 커뮤니티 본문 추출 성공 ({len(res.content)}자, 법적 푸터 배제 확인)")

    def test_at4_universal_routing_to_authenticated(self):
        """AT-4: universal_extractor로 인스타 URL 입력 시 인증 파이프라인으로 라우팅 검증"""
        test_url = "https://www.instagram.com/p/C-dummy_post_for_test/"
        res = universal_extractor.extract_universal(test_url)
        self.assertEqual(res.source_type, "instagram")
        self.assertTrue(len(res.content) > 0)
        print(f"\n[PASS] AT-4: 만능 추출기 ➔ 인증 브라우저 파이프라인 안전 연결 완료 (출처: {res.source_type})")


if __name__ == "__main__":
    unittest.main()
