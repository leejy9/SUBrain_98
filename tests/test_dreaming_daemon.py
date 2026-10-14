import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

# daemon 경로 추가
daemon_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "daemon"))
if daemon_path not in sys.path:
    sys.path.insert(0, daemon_path)

from dreaming_daemon import DreamingDaemon
from moc_service import MOCService

def test_dreaming_daemon_audit_structure():
    """DreamingDaemon의 MOC 적합성 감사 인터페이스 검증"""
    mock_moc_service = MagicMock(spec=MOCService)
    mock_moc_service.get_moc_children.return_value = ["경험_팀원갈등조정", "지식_양자컴퓨팅"]

    daemon = DreamingDaemon(moc_service=mock_moc_service)

    # 1. 자식 노드가 없을 때의 방어 검증
    mock_moc_service.get_moc_children.return_value = []
    res_empty = daemon.audit_moc_relevance("MOC_커리어")
    assert res_empty["drift_detected"] is False
    assert res_empty["total_nodes"] == 0
    assert "건너뜁니다" in res_empty["natural_briefing"]

def test_dreaming_daemon_split_structure():
    """DreamingDaemon의 MOC 이질성 분할 진단 인터페이스 검증"""
    mock_moc_service = MagicMock(spec=MOCService)
    # 노드가 5개 미만일 때 (분할 불필요)
    mock_moc_service.get_moc_children.return_value = ["경험_A", "경험_B"]

    daemon = DreamingDaemon(moc_service=mock_moc_service)
    res_small = daemon.diagnose_moc_heterogeneity("MOC_커리어")
    assert res_small["split_recommended"] is False
    assert res_small["heterogeneity_level"] == "낮음"
    assert "건강한 상태" in res_small["natural_briefing"]

if __name__ == "__main__":
    print("=== Phase 4: The Dreaming Daemon 단위 테스트 실행 ===")
    test_dreaming_daemon_audit_structure()
    print("--> 1. MOC 소속 적합성 인터페이스 PASS!")
    test_dreaming_daemon_split_structure()
    print("--> 2. MOC 이질성 분할 인터페이스 PASS!")
    print("\n✅ Dreaming Daemon 인터페이스 테스트 전원 통과 (Green State)!")
