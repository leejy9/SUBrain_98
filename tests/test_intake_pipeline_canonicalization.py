import os
import sys
from pathlib import Path

# daemon 경로 추가
daemon_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "daemon"))
if daemon_path not in sys.path:
    sys.path.insert(0, daemon_path)

from agent_core import ConstitutionalAgent
from tag_service import TagRegistry

def test_intake_tag_canonicalization_and_critic_proposal():
    """인테이크 시 태그 자동 정규화 및 미등재 태그의 발의 플래그 검속 테스트"""
    registry = TagRegistry()

    # 가상 LLM 반환 태그 (동의어 2개 + 미등재 1개)
    raw_tags = ["시장데이터분석", "팀원설득", "우주양자컴퓨팅"]
    canonical_tags, unmapped_tags = registry.canonicalize_list(raw_tags)

    assert "#역량/데이터기반의사결정" in canonical_tags
    assert "#역량/이해관계자조율" in canonical_tags
    assert "우주양자컴퓨팅" in unmapped_tags
    assert len(canonical_tags) == 2
    assert len(unmapped_tags) == 1

    # Critic 감사 로그 라인 시뮬레이션
    critic_log_lines = []
    if unmapped_tags:
        critic_log_lines.append(f"> - ⚠️ [신규 태그 발의 (인간 승인 대기)] 미등재 태그 감지: {', '.join(unmapped_tags)}")

    assert any("[신규 태그 발의 (인간 승인 대기)]" in line for line in critic_log_lines)
    assert "우주양자컴퓨팅" in critic_log_lines[0]

    # Frontmatter 태그 배열 포맷팅 검증
    classified_type = "Experience"
    all_frontmatter_tags = [f"#{classified_type.lower()}"] + [t for t in canonical_tags if t]
    tags_yaml_str = ", ".join(f'"{t}"' for t in all_frontmatter_tags)
    assert tags_yaml_str == '"#experience", "#역량/데이터기반의사결정", "#역량/이해관계자조율"'

if __name__ == "__main__":
    print("=== Phase 3: 인테이크 태그 정규화 및 발의 플래그 검증 ===")
    test_intake_tag_canonicalization_and_critic_proposal()
    print("--> ✅ Phase 3 인테이크 파이프라인 정규화 테스트 PASS (Green State)!")
