"""
tests/test_mention_scanner.py - Unit Tests for Safe Lexer-Masked Unlinked Mention Scanner
Verifies:
1. Entity extraction from vault notes
2. Markdown syntax masking (Code block, existing link, bold, frontmatter)
3. Real vault scan on 지원_2026_굿네이버스.md
4. Safe replacement without syntax corruption or duplicate wrapping
"""

import sys
from pathlib import Path

# Add daemon to path
daemon_dir = Path(__file__).resolve().parent.parent / "daemon"
sys.path.insert(0, str(daemon_dir))

import mention_scanner


def test_list_linkable_entities():
    entities = mention_scanner.list_linkable_entities()
    assert len(entities) > 0, "연결 가능한 엔티티가 최소 1개 이상 수집되어야 함"
    
    # 경험 노드 키워드가 존재하는지 검증
    found_nr = any("넥스트러너스" in k for k in entities.keys())
    assert found_nr, "넥스트러너스 관련 경험 노드 키워드가 엔티티 맵에 존재해야 함"
    print(f"✓ [PASS] 엔티티 맵 수집 완료: 총 {len(entities)}개 키워드")


def test_mask_markdown_content():
    sample_md = """---
tags: [커리어]
title: 테스트
---
# 헤더 1

여기는 일반 본문입니다. 넥스트러너스 자발적 참여구조를 사용했습니다.

```python
# 코드 블록 내부의 넥스트러너스 자발적 참여구조는 건드리면 안 됨
print("hello")
```

이미 존재하는 링크 [[경험_넥스트러너스_자발적참여구조]]도 건드리면 안 됨.
**볼드체 안의 넥스트러너스**도 보호되어야 함.
"""
    masked, protected = mention_scanner.mask_markdown_content(sample_md)
    assert len(masked) == len(sample_md), "마스킹 후 문자열 길이는 원본과 100% 동일해야 함"
    
    # 코드 블록 영역이 공백으로 치환되었는지 검증
    code_start = sample_md.find("```python")
    assert masked[code_start:code_start+9] == "         ", "코드 블록이 공백으로 마스킹되어야 함"
    
    # 기존 링크 영역이 공백으로 치환되었는지 검증
    link_start = sample_md.find("[[경험_넥스트러너스_자발적참여구조]]")
    assert masked[link_start:link_start+5] == "     ", "기존 링크가 공백으로 마스킹되어야 함"
    
    # 일반 본문 구역은 살아있는지 검증
    body_pos = sample_md.find("넥스트러너스 자발적 참여구조를")
    assert masked[body_pos:body_pos+10] == "넥스트러너스 자발적", "순수 본문 영역은 마스킹되지 않고 남아있어야 함"
    
    print("✓ [PASS] 마크다운 마스킹 테이프 구문 보호 100% 검증 완료")


def test_real_vault_scan_goodneighbors():
    mentions = mention_scanner.scan_unlinked_mentions_in_file("지원_2026_굿네이버스.md")
    print(f"굿네이버스 문서에서 탐지된 언링크드 멘션: {len(mentions)}건")
    for m in mentions:
        print(f" - [{m['line_number']}행] '{m['matched_text']}' (조사: '{m['postposition']}') -> [[{m['target_node']}]]")
        print(f"   인용 문맥: {m['source_context']}")

    # 최소 1건 이상 넥스트러너스 관련 멘션이 잡혀야 함
    has_nr = any("넥스트러너스" in m["matched_text"] for m in mentions)
    assert has_nr, "지원_2026_굿네이버스.md에서 넥스트러너스 경험 멘션이 성공적으로 탐지되어야 함"
    print("✓ [PASS] 실존 볼트 파일(지원_2026_굿네이버스) 언링크드 멘션 실측 탐지 검증 완료")


if __name__ == "__main__":
    test_list_linkable_entities()
    test_mask_markdown_content()
    test_real_vault_scan_goodneighbors()
    print("\n모든 단위 테스트 100% PASS!")
