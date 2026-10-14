"""
daemon/subconscious_service.py - Subconscious Memory Archive & Custom Retention Daemon
SUBrain_98 Architecture Invariant:
1. "정리하지 않은 것은 당신의 나태가 아니라, 뇌의 자연스러운 필터링(Active Forgetfulness)입니다."
2. Inbox Zero 죄책감 해소: 유효기간(기본 14일)이 지난 미결 카드는 삭제가 아니라 '무의식 보관소'로 조용히 침잠.
3. 2계층 인출: 글로벌 검색(⌘K) 시 1계층 지식망 하단에 후순위 스크롤로만 노출.
"""

import json
import logging
import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional

from config import VAULT_DIR

logger = logging.getLogger(__name__)

SETTINGS_FILE = Path(__file__).parent / "subconscious_settings.json"
CARDS_FILE = Path(__file__).parent / "cards.json"
SUBCONSCIOUS_DIR = VAULT_DIR / "_subconscious"

DEFAULT_SETTINGS = {
    "retention_days": 14, # 기본 14일 (7일, 14일, 30일, 0=무제한)
    "auto_archive_enabled": True,
    "philosophy_quote": "정리하지 않은 것은 당신의 나태가 아니라, 뇌가 지금 당장 불필요하다고 판단한 건강한 망각입니다. 무의식 보관소에 안전하게 잠재워둡니다."
}


class SubconsciousArchiveService:
    def __init__(self):
        SUBCONSCIOUS_DIR.mkdir(parents=True, exist_ok=True)
        self.settings = self.load_settings()

    def load_settings(self) -> Dict[str, Any]:
        if not SETTINGS_FILE.exists():
            self.save_settings(DEFAULT_SETTINGS)
            return DEFAULT_SETTINGS.copy()
        try:
            return json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        except Exception as e:
            logger.error(f"[Subconscious] 설정 로드 실패: {e}")
            return DEFAULT_SETTINGS.copy()

    def save_settings(self, new_settings: Dict[str, Any]):
        curr = getattr(self, "settings", DEFAULT_SETTINGS.copy())
        self.settings = {**curr, **new_settings}
        SETTINGS_FILE.write_text(json.dumps(self.settings, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info(f"[Subconscious] 보관 주기 설정 갱신: {self.settings.get('retention_days')}일")

    def archive_expired_cards(self, cards_dict: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """
        보관 주기(retention_days)가 지난 PENDING 상태의 카드를 무의식 보관소로 조용히 이전.
        """
        retention_days = self.settings.get("retention_days", 14)
        if retention_days <= 0: # 0은 무제한(자동 보관 끔)
            return []

        now = datetime.datetime.now()
        archived_items = []

        # 1. cards_dict 또는 CARDS_FILE 로드
        target_cards = cards_dict
        if target_cards is None and CARDS_FILE.exists():
            try:
                target_cards = json.loads(CARDS_FILE.read_text(encoding="utf-8"))
            except Exception:
                target_cards = {}

        if not target_cards:
            return []

        modified = False
        for card_id, card in target_cards.items():
            status = card.get("status", "PENDING")
            if status != "PENDING":
                continue

            created_at_str = card.get("created_at")
            if not created_at_str:
                continue

            try:
                # ISO 포맷 파싱
                dt = datetime.datetime.fromisoformat(created_at_str.replace("Z", "+00:00"))
                # timezone offset 제거하여 naive 비교
                if dt.tzinfo:
                    dt = dt.replace(tzinfo=None)
                age_days = (now - dt).total_seconds() / 86400.0

                if age_days >= retention_days:
                    card["status"] = "SUBCONSCIOUS_ARCHIVED"
                    card["subconscious_archived_at"] = now.isoformat()
                    card["subconscious_archive_reason"] = (
                        f"인박스 유효기간({retention_days}일) 만료로 인한 건강한 망각 침잠. "
                        f"사용자 인지 부하 0 리셋 완료."
                    )
                    archived_items.append({
                        "id": card_id,
                        "title": card.get("title", ""),
                        "age_days": round(age_days, 1),
                        "archived_at": card["subconscious_archived_at"]
                    })
                    modified = True
                    logger.info(f"[Subconscious] 카드 '{card.get('title')}' 무의식 보관소로 침잠 ({round(age_days, 1)}일 경과)")
            except Exception as e:
                logger.warning(f"[Subconscious] 날짜 파싱 오류: {card_id} -> {e}")

        if modified and CARDS_FILE.exists():
            try:
                CARDS_FILE.write_text(json.dumps(target_cards, ensure_ascii=False, indent=2), encoding="utf-8")
            except Exception as e:
                logger.error(f"[Subconscious] cards.json 저장 실패: {e}")

        return archived_items

    def search_subconscious_archive(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        """
        글로벌 검색(⌘K) 시 2계층 인출:
        무의식 보관소에 침잠된 카드 중에서 질의어와 관련된 카드를 후순위로 추출.
        """
        if not CARDS_FILE.exists() or not query.strip():
            return []

        try:
            all_cards = json.loads(CARDS_FILE.read_text(encoding="utf-8"))
        except Exception:
            return []

        q = query.lower().strip()
        matched = []

        for card_id, card in all_cards.items():
            if card.get("status") != "SUBCONSCIOUS_ARCHIVED":
                continue

            title = card.get("title", "").lower()
            content = card.get("content", "").lower()
            md = card.get("markdown_content", "").lower()

            if q in title or q in content or q in md:
                matched.append({
                    "id": card_id,
                    "title": card.get("title", ""),
                    "summary": card.get("one_line_summary") or card.get("content", "")[:100],
                    "archived_at": card.get("subconscious_archived_at", ""),
                    "reason": card.get("subconscious_archive_reason", ""),
                    "tags": card.get("tags", []),
                    "status": "SUBCONSCIOUS_ARCHIVED"
                })
                if len(matched) >= limit:
                    break

        return matched

    def list_subconscious_cards(self, cards_dict: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """
        무의식 보관소에 잠든 모든 카드 목록을 침잠 시간 역순으로 반환.
        각 카드에 잠든 일수(dormant_days)를 계산하여 사용자 친화적으로 제공.
        """
        target_cards = cards_dict
        if target_cards is None and CARDS_FILE.exists():
            try:
                target_cards = json.loads(CARDS_FILE.read_text(encoding="utf-8"))
            except Exception:
                target_cards = {}

        if not target_cards:
            return []

        now = datetime.datetime.now()
        results = []

        for card_id, card in target_cards.items():
            if card.get("status") != "SUBCONSCIOUS_ARCHIVED":
                continue

            archived_at_str = card.get("subconscious_archived_at")
            dormant_days = 0
            if archived_at_str:
                try:
                    dt = datetime.datetime.fromisoformat(archived_at_str.replace("Z", "+00:00"))
                    if dt.tzinfo:
                        dt = dt.replace(tzinfo=None)
                    dormant_days = max(0, round((now - dt).total_seconds() / 86400.0, 1))
                except Exception:
                    pass

            results.append({
                "id": card_id,
                "title": card.get("title", "무제 메모"),
                "content": card.get("content", ""),
                "one_line_summary": card.get("one_line_summary") or card.get("content", "")[:120],
                "markdown_content": card.get("markdown_content", ""),
                "tags": card.get("tags", []),
                "moc": card.get("moc", "MOC_아이디어"),
                "created_at": card.get("created_at", ""),
                "archived_at": archived_at_str,
                "dormant_days": dormant_days,
                "reason": card.get("subconscious_archive_reason", "인박스 보관 만료"),
                "status": "SUBCONSCIOUS_ARCHIVED"
            })

        results.sort(key=lambda x: x.get("archived_at") or "", reverse=True)
        return results

    def restore_card_to_inbox(self, card_id: str, cards_dict: Optional[Dict[str, Any]] = None) -> bool:
        """
        무의식 보관소에 잠든 카드를 다시 살아있는 인박스(PENDING)로 깨워 복원.
        """
        target_cards = cards_dict
        if target_cards is None and CARDS_FILE.exists():
            try:
                target_cards = json.loads(CARDS_FILE.read_text(encoding="utf-8"))
            except Exception:
                target_cards = {}

        if not target_cards or card_id not in target_cards:
            logger.warning(f"[Subconscious] 복원 대상 카드 없음: {card_id}")
            return False

        card = target_cards[card_id]
        card["status"] = "PENDING"
        card.pop("subconscious_archived_at", None)
        card.pop("subconscious_archive_reason", None)
        card["restored_at"] = datetime.datetime.now().isoformat()

        if CARDS_FILE.exists():
            try:
                CARDS_FILE.write_text(json.dumps(target_cards, ensure_ascii=False, indent=2), encoding="utf-8")
                logger.info(f"[Subconscious] 카드 '{card.get('title')}' 인박스로 부활/복원 완료!")
                return True
            except Exception as e:
                logger.error(f"[Subconscious] 복원 저장 실패: {e}")
                return False
        return True

    def delete_subconscious_card(self, card_id: str, cards_dict: Optional[Dict[str, Any]] = None) -> bool:
        """
        무의식 보관소의 카드를 완전히 묘비(TOMBSTONE)로 폐기 처리.
        """
        target_cards = cards_dict
        if target_cards is None and CARDS_FILE.exists():
            try:
                target_cards = json.loads(CARDS_FILE.read_text(encoding="utf-8"))
            except Exception:
                target_cards = {}

        if not target_cards or card_id not in target_cards:
            return False

        card = target_cards[card_id]
        card["status"] = "TOMBSTONE"
        card["tombstone_at"] = datetime.datetime.now().isoformat()
        card["tombstone_reason"] = "무의식 보관소에서 사용자 수동 영구 폐기"

        if CARDS_FILE.exists():
            try:
                CARDS_FILE.write_text(json.dumps(target_cards, ensure_ascii=False, indent=2), encoding="utf-8")
                logger.info(f"[Subconscious] 카드 '{card.get('title')}' 영구 묘비 폐기 완료")
                return True
            except Exception as e:
                logger.error(f"[Subconscious] 삭제 저장 실패: {e}")
                return False
        return True
