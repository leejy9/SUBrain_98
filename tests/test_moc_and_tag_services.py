import os
import shutil
import tempfile
from pathlib import Path

from daemon.tag_service import TagRegistry
from daemon.moc_service import MOCService, CONSTITUTIONAL_MOCS

def test_tag_registry_canonicalization():
    """실제 볼트의 00_태그사전.md를 기반으로 정규화 테스트"""
    registry = TagRegistry()
    assert len(registry.canonical_tags) > 0, "공식 태그가 1개 이상 로드되어야 함"

    # 동의어 매핑 테스트
    canon1, ok1 = registry.canonicalize("시장데이터분석")
    assert ok1 is True
    assert canon1 == "#역량/데이터기반의사결정"

    canon2, ok2 = registry.canonicalize("팀원설득")
    assert ok2 is True
    assert canon2 == "#역량/이해관계자조율"

    canon3, ok3 = registry.canonicalize("예산부족")
    assert ok3 is True
    assert canon3 == "#상황/자원결핍"

    canon4, ok4 = registry.canonicalize("에듀테크")
    assert ok4 is True
    assert canon4 == "#도메인/에듀테크"

    # 이미 정규화된 태그
    canon5, ok5 = registry.canonicalize("#역량/사업기획및BM설계")
    assert ok5 is True
    assert canon5 == "#역량/사업기획및BM설계"

    # 사전에 없는 미등재 태그
    canon6, ok6 = registry.canonicalize("초거대우주비행")
    assert ok6 is False

    # 일괄 정규화 및 분리 테스트
    tags = ["시장데이터분석", "예산부족", "신규외계물질"]
    mapped, unmapped = registry.canonicalize_list(tags)
    assert "#역량/데이터기반의사결정" in mapped
    assert "#상황/자원결핍" in mapped
    assert "신규외계물질" in unmapped

    # 발의 객체 생성 테스트
    prop = registry.propose_new_tag("신규외계물질", "역량", "외계 탐사 프로젝트 경험에 필요")
    assert prop["type"] == "tag_proposal"
    assert prop["proposed_tag"] == "#역량/신규외계물질"
    assert prop["status"] == "pending_hitl_approval"

def test_moc_service_lifecycle_in_isolated_vault():
    """임시 가상 볼트 환경에서 MOC 라이프사이클 및 불변식 테스트"""
    with tempfile.TemporaryDirectory() as temp_dir:
        fake_vault = Path(temp_dir)

        # 4대 헌법 MOC 파일 생성
        for moc in CONSTITUTIONAL_MOCS:
            (fake_vault / f"{moc}.md").write_text(f"# {moc}\n본문 내용", encoding="utf-8")

        # 가상 자식 노드 생성
        sample_node = fake_vault / "테스트경험.md"
        sample_node.write_text(
            '---\ntitle: 테스트경험\nmoc: "[[MOC_커리어]]"\n---\n# 테스트\n[[MOC_커리어]] 관련 메모',
            encoding="utf-8"
        )

        service = MOCService(vault_dir=fake_vault)

        # 1. MOC 목록 조회
        mocs = service.list_mocs()
        assert len(mocs) == 4
        career_moc = next(m for m in mocs if m["name"] == "MOC_커리어")
        assert career_moc["children_count"] == 1
        assert "테스트경험" in career_moc["children"]

        # 2. 하위 MOC 생성 (2계층) 및 노드 이전
        sub_moc_path = service.create_sub_moc(
            name="MOC_커리어_핀테크",
            parent_moc="MOC_커리어",
            description="핀테크 및 금융 데이터 프로젝트 모음",
            initial_nodes=["테스트경험"]
        )
        assert sub_moc_path.exists()

        # 상위 MOC에 하위 성단 링크가 등록되었는지 확인
        parent_content = (fake_vault / "MOC_커리어.md").read_text(encoding="utf-8")
        assert "[[MOC_커리어_핀테크]]" in parent_content

        # 노드의 MOC가 하위 MOC로 변경되었는지 확인
        node_content = sample_node.read_text(encoding="utf-8")
        assert 'moc: "[[MOC_커리어_핀테크]]"' in node_content

        # 3. 2계층 초과 생성 방지 (하위 MOC를 부모로 삼으려 할 때)
        try:
            service.create_sub_moc(
                name="MOC_커리어_핀테크_결제",
                parent_moc="MOC_커리어_핀테크",
                description="3계층 시도"
            )
            assert False, "3계층 생성은 예외가 발생해야 함"
        except ValueError:
            pass

        # 4. 헌법 MOC 삭제 시도 방지 (PermissionError)
        try:
            service.safe_delete_moc("MOC_커리어", fallback_moc="MOC_지식원리")
            assert False, "헌법 MOC 삭제는 거부되어야 함"
        except PermissionError:
            pass

        # 5. 하위 MOC 안전 삭제 및 자식 노드 안전 대피 (고아 방지)
        deleted = service.safe_delete_moc("MOC_커리어_핀테크", fallback_moc="MOC_커리어")
        assert deleted is True
        assert not sub_moc_path.exists()

        # 자식 노드가 fallback_moc로 복귀되었는지 확인
        node_content_after = sample_node.read_text(encoding="utf-8")
        assert 'moc: "[[MOC_커리어]]"' in node_content_after

if __name__ == "__main__":
    print("=== 1. TagRegistry 단위 테스트 실행 ===")
    test_tag_registry_canonicalization()
    print("--> TagRegistry 단위 테스트 PASS!")

    print("=== 2. MOCService 라이프사이클 단위 테스트 실행 ===")
    test_moc_service_lifecycle_in_isolated_vault()
    print("--> MOCService 단위 테스트 PASS!")
    print("\n✅ 모든 단위 테스트 정상 통과 (Green State)!")

