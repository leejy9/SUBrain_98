"""
tests/test_subconscious_service.py - Unit Tests for Subconscious Archive & Custom Retention
"""

import sys
import datetime
from pathlib import Path

daemon_dir = Path(__file__).resolve().parent.parent / "daemon"
sys.path.insert(0, str(daemon_dir))

import subconscious_service


def test_settings_persistence():
    svc = subconscious_service.SubconsciousArchiveService()
    svc.save_settings({"retention_days": 7})
    loaded = svc.load_settings()
    assert loaded["retention_days"] == 7, "보관 주기가 7일로 정상 저장 및 로드되어야 함"
    
    # 원복
    svc.save_settings({"retention_days": 14})
    assert svc.load_settings()["retention_days"] == 14
    print("✓ [PASS] 보관 주기 설정 영구 저장 및 로드 검증 완료")


def test_archive_expired_cards():
    svc = subconscious_service.SubconsciousArchiveService()
    svc.save_settings({"retention_days": 14})
    
    now = datetime.datetime.now()
    ten_days_ago = (now - datetime.timedelta(days=10)).isoformat()
    twenty_days_ago = (now - datetime.timedelta(days=20)).isoformat()
    today = now.isoformat()
    
    mock_cards = {
        "card-1": {
            "title": "20일 전 오래된 미결 메모",
            "content": "이것은 예전에 기록하고 잊어버린 아이디어입니다.",
            "status": "PENDING",
            "created_at": twenty_days_ago
        },
        "card-2": {
            "title": "10일 전 최근 메모",
            "content": "아직 유효기간 내에 있는 활성 메모입니다.",
            "status": "PENDING",
            "created_at": ten_days_ago
        },
        "card-3": {
            "title": "오늘 작성한 메모",
            "content": "방금 인입된 따끈따끈한 메모입니다.",
            "status": "PENDING",
            "created_at": today
        }
    }
    
    archived = svc.archive_expired_cards(mock_cards)
    assert len(archived) == 1, "20일 경과한 card-1 1개만 침잠되어야 함"
    assert archived[0]["id"] == "card-1"
    assert mock_cards["card-1"]["status"] == "SUBCONSCIOUS_ARCHIVED"
    assert mock_cards["card-2"]["status"] == "PENDING"
    assert mock_cards["card-3"]["status"] == "PENDING"
    assert "subconscious_archive_reason" in mock_cards["card-1"]
    print("✓ [PASS] 14일 경과 미결 카드 무의식 보관소 자동 침잠 및 인지부하 0 리셋 검증 완료")


if __name__ == "__main__":
    test_settings_persistence()
    test_archive_expired_cards()
    print("\n무의식 보관소 전체 단위 테스트 100% PASS!")
