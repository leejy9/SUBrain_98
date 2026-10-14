import sys
from pathlib import Path

# daemon 경로 추가
daemon_path = Path(__file__).parent.parent / "daemon"
if str(daemon_path) not in sys.path:
    sys.path.insert(0, str(daemon_path))

from scoring_engine import ScoringEngine
from models import TriageRecommendation, IngestScoreMetadata


def test_information_density_numeric_and_tech():
    text_with_dense_info = (
        "2026년 3분기 기준 Redis 캐시 레이턴시를 35% 절감하여 12,000 TPS 처리량을 달성함. "
        "PostgreSQL 분산 파이프라인의 동시성 병목을 해결하고 월 4,500만원 비용 절감."
    )
    density = ScoringEngine.calculate_information_density(text_with_dense_info)
    assert density > 50.0, f"Expected density > 50.0, got {density}"

    text_plain = "오늘 날씨가 참 좋았다. 점심을 먹고 산책을 했다."
    density_plain = ScoringEngine.calculate_information_density(text_plain)
    assert density_plain < 15.0, f"Expected plain text density < 15.0, got {density_plain}"
    print(f"✓ test_information_density_numeric_and_tech passed: dense={density}, plain={density_plain}")


def test_vault_proximity():
    mock_vault_notes = [
        {"name": "지식_클로드코드_폴더구조", "h1": "클로드 코드 폴더 구조"},
        {"name": "지식_하이브리드_추론엔진", "h1": "하이브리드 추론 엔진"},
        {"name": "경험_이력서구조화전략", "h1": "이력서 구조화 전략"},
    ]
    text = "클로드 코드의 4개 폴더 구조와 하이브리드 추론 엔진을 연계하여 아키텍처를 설계함."
    prox = ScoringEngine.calculate_vault_proximity(text, mock_vault_notes)
    assert prox > 40.0, f"Expected proximity > 40.0, got {prox}"
    print(f"✓ test_vault_proximity passed: prox={prox}")


def test_intent_boost():
    assert ScoringEngine.calculate_intent_boost("") == 0.0
    assert ScoringEngine.calculate_intent_boost("a") == 0.0
    assert ScoringEngine.calculate_intent_boost("이 기술은 백엔드 캐시용임") == 20.0
    print("✓ test_intent_boost passed")


def test_compute_score_fast_track_vs_deep_tune():
    # 1. 단순 기사 (수치/전문어 적고 메모 없음) -> FAST_TRACK_ELIGIBLE
    plain_article = "구글이 새로운 AI 모델 업데이트를 발표했습니다. 사용자 피드백을 수렴한다고 밝혔습니다."
    score_plain = ScoringEngine.compute_score(plain_article, user_context="", vault_notes=[])
    assert score_plain.triage_recommendation == TriageRecommendation.FAST_TRACK_ELIGIBLE
    assert score_plain.total_score < 75.0

    # 2. 고밀도 + 볼트 연관 노드 + 메모 동봉 -> DEEP_TUNE_RECOMMENDED
    dense_tech = (
        "2026년 Redis 클러스터 장애 극복을 위해 45% 레이턴시 개선과 50,000 QPS를 확보한 PostgreSQL 분산 파이프라인. "
        "Kafka MQ 아키텍처 연계로 1억 2천만원 서버 비용 절감."
    )
    score_deep = ScoringEngine.compute_score(
        dense_tech,
        user_context="우리 결제 서비스 분산 락 정책과 직접 충돌할 수 있으니 검증 필수",
        vault_notes=[
            {"name": "지식_분산_파이프라인", "h1": "분산 파이프라인 아키텍처"},
            {"name": "지식_하이브리드_추론엔진", "h1": "추론엔진"}
        ]
    )
    assert score_deep.triage_recommendation == TriageRecommendation.DEEP_TUNE_RECOMMENDED
    assert score_deep.total_score >= 75.0
    print(f"✓ test_compute_score passed: plain={score_plain.total_score} ({score_plain.triage_recommendation.value}), deep={score_deep.total_score} ({score_deep.triage_recommendation.value})")


def test_devil_advocate_copilot_execution():
    from agent_core import ConstitutionalAgent
    agent = ConstitutionalAgent()

    result = agent.execute_devil_advocate_copilot(
        title="분산 캐시 레이턴시 최적화",
        filename="지식_분산캐시_최적화.md",
        markdown_content="""# 지식_분산캐시_최적화
## 1. 한 줄 요약
Redis 기반 캐시를 적용하여 백엔드 레이턴시를 절감함.
## 📌 핵심 내용
동시성 요청 50,000 TPS 환경에서 캐시 힛율을 98%로 유지.""",
        prompt="이 기술을 우리 결제 세션 저장소에 도입하려고 하는데, 트레이드오프가 뭐야?",
        synthesis="Redis 캐시로 레이턴시를 줄임"
    )

    assert "assistant_response" in result
    resp = result["assistant_response"]
    assert len(resp) > 20
    # Sycophancy 검증: 기계적 아첨 문구가 없는지 확인
    assert "좋은 생각입니다" not in resp and "훌륭한 통찰" not in resp
    print(f"✓ test_devil_advocate_copilot_execution passed: response sample -> {resp[:120]}...")


if __name__ == "__main__":
    test_information_density_numeric_and_tech()
    test_vault_proximity()
    test_intent_boost()
    test_compute_score_fast_track_vs_deep_tune()
    test_devil_advocate_copilot_execution()
    print("\n🎉 모든 스코어링 엔진 및 악마의 대변인 하네스 검증 완료!")
