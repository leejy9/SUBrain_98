import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Set, Any
try:
    from config import VAULT_DIR
except ImportError:
    from daemon.config import VAULT_DIR

CONSTITUTIONAL_MOCS = {
    "MOC_커리어",
    "MOC_지식원리",
    "MOC_지원전략_합격패턴",
    "MOC_아이디어"
}

class MOCService:
    """
    Subrain_98 MOC(Map of Content) 거버넌스 및 라이프사이클 관리 서비스.
    규칙:
    1. 최상위 4대 헌법 MOC는 불변 및 삭제 불가.
    2. 하위 MOC는 최대 2계층(최상위 -> 하위)까지만 허용.
    3. 하위 MOC 삭제 시 모든 자식 노드는 fallback_moc로 안전 대피 (고아 노드 원천 차단).
    4. AI의 임의 MOC 파일 생성 금지 (서비스 매크로 호출 및 명시적 인터페이스 통제).
    """

    def __init__(self, vault_dir: Optional[Path] = None):
        self.vault_dir = vault_dir or VAULT_DIR

    def _normalize_moc_name(self, moc_name: str) -> str:
        """MOC 이름 표준화 (확장자 및 대괄호 제거)"""
        clean = moc_name.replace("[[", "").replace("]]", "").strip()
        if clean.endswith(".md"):
            clean = clean[:-3]
        return clean

    def list_mocs(self) -> List[Dict]:
        """볼트 내 모든 MOC 파일 목록 및 계층 구조, 자식 노드 통계 반환"""
        mocs = []
        for file in self.vault_dir.glob("MOC_*.md"):
            moc_name = file.stem
            content = file.read_text(encoding="utf-8")

            # 하위 MOC 여부 판별 (frontmatter parent_moc 확인)
            parent_match = re.search(r"parent_moc:\s*\[?\[?([^\]\n]+)\]?\]?", content)
            parent_moc = self._normalize_moc_name(parent_match.group(1)) if parent_match else None
            is_constitutional = moc_name in CONSTITUTIONAL_MOCS

            # 자식 노드 검색
            children = self.get_moc_children(moc_name)

            mocs.append({
                "name": moc_name,
                "file_path": str(file),
                "is_constitutional": is_constitutional,
                "is_sub_moc": parent_moc is not None,
                "parent_moc": parent_moc,
                "children_count": len(children),
                "children": children
            })
        return mocs

    def get_moc_children(self, moc_name: str) -> List[str]:
        """특정 MOC에 소속된 자식 노드 목록 검색"""
        norm_name = self._normalize_moc_name(moc_name)
        children = []

        for note_file in self.vault_dir.glob("*.md"):
            if note_file.name.startswith("MOC_") or note_file.name.startswith("00_"):
                continue
            try:
                content = note_file.read_text(encoding="utf-8")
                # 1. Frontmatter moc 확인
                fm_match = re.search(r"moc:\s*\[?\[?([^\]\n]+)\]?\]?", content)
                if fm_match and self._normalize_moc_name(fm_match.group(1)) == norm_name:
                    children.append(note_file.stem)
                    continue

                # 2. 본문 상단 MOC 링크 확인
                if f"[[{norm_name}]]" in content:
                    children.append(note_file.stem)
            except Exception:
                continue

        return children

    def create_sub_moc(
        self,
        name: str,
        parent_moc: str,
        description: str,
        initial_nodes: Optional[List[str]] = None
    ) -> Path:
        """
        하위 MOC(2계층) 신설 및 상위 MOC 결속, 초기 노드 이전.
        """
        norm_parent = self._normalize_moc_name(parent_moc)
        if norm_parent not in CONSTITUTIONAL_MOCS:
            # 2계층 제한: 하위 MOC의 부모는 반드시 최상위 헌법 MOC여야 함
            raise ValueError(f"하위 MOC의 부모는 4대 헌법 MOC 중 하나여야 합니다: {norm_parent}")

        norm_name = self._normalize_moc_name(name)
        if not norm_name.startswith("MOC_"):
            norm_name = f"MOC_{norm_name}"

        file_path = self.vault_dir / f"{norm_name}.md"
        if file_path.exists():
            raise FileExistsError(f"이미 존재하는 MOC 파일입니다: {norm_name}")

        today = datetime.now().strftime("%Y-%m-%d")
        sub_moc_content = f"""---
type: sub_moc
parent_moc: [[{norm_parent}]]
created_at: {today}
---

# {norm_name}

> [!NOTE]
> 본 문서는 [[{norm_parent}]] 산하의 **하위 지식 성단(Sub-MOC)**입니다.

## 📌 목적 및 맥락
{description.strip()}

## 🌌 소속 노드 (Nodes)
<!-- nodes_start -->
<!-- nodes_end -->

---
- 상위 허브: [[{norm_parent}]]
"""
        file_path.write_text(sub_moc_content, encoding="utf-8")

        # 상위 MOC 파일에 하위 MOC 링크 등록
        parent_file = self.vault_dir / f"{norm_parent}.md"
        if parent_file.exists():
            p_content = parent_file.read_text(encoding="utf-8")
            link_entry = f"- 🪐 [[{norm_name}]]: {description.strip().splitlines()[0]}"
            if f"[[{norm_name}]]" not in p_content:
                p_content += f"\n\n### 🪐 하위 성단 (Sub-MOCs)\n{link_entry}\n"
                parent_file.write_text(p_content, encoding="utf-8")

        # 초기 노드가 있으면 일괄 이전
        if initial_nodes:
            self.batch_reassign_nodes(initial_nodes, norm_name)

        return file_path

    def reassign_node_moc(self, note_name: str, target_moc: str) -> bool:
        """
        개별 노드의 MOC 소속을 안전하게 target_moc로 갱신.
        Frontmatter 및 본문 링크 원자적 수정.
        """
        norm_target = self._normalize_moc_name(target_moc)
        note_stem = note_name.replace(".md", "").strip()
        note_file = self.vault_dir / f"{note_stem}.md"

        if not note_file.exists():
            return False

        content = note_file.read_text(encoding="utf-8")

        # Frontmatter moc 필드 치환
        if re.search(r"^moc:\s*.*$", content, flags=re.MULTILINE):
            new_content = re.sub(
                r"^moc:\s*.*$",
                f'moc: "[[{norm_target}]]"',
                content,
                flags=re.MULTILINE
            )
        else:
            # Frontmatter에 moc 필드가 없으면 추가
            if content.startswith("---"):
                parts = content.split("---", 2)
                if len(parts) >= 3:
                    new_fm = parts[1].strip() + f'\nmoc: "[[{norm_target}]]"\n'
                    new_content = f"---{new_fm}---" + parts[2]
                else:
                    new_content = content
            else:
                new_content = content

        # 본문 내 MOC 링크 갱신
        new_content = re.sub(r"\[\[MOC_[^\]]+\]\]", f"[[{norm_target}]]", new_content, count=1)

        note_file.write_text(new_content, encoding="utf-8")
        return True

    def batch_reassign_nodes(self, note_names: List[str], target_moc: str) -> Dict[str, bool]:
        """다수의 노드를 target_moc로 일괄 이전"""
        results = {}
        for name in note_names:
            results[name] = self.reassign_node_moc(name, target_moc)
        return results

    def safe_delete_moc(self, moc_name: str, fallback_moc: str) -> bool:
        """
        하위 MOC 안전 삭제 매크로.
        1. 4대 헌법 MOC 삭제 시도시 거부.
        2. 소속 자식 노드들을 fallback_moc로 전수 이전 후 파일 삭제 (고아 노드 방지).
        """
        norm_name = self._normalize_moc_name(moc_name)
        if norm_name in CONSTITUTIONAL_MOCS:
            raise PermissionError(f"4대 헌법 MOC는 삭제할 수 없습니다: {norm_name}")

        norm_fallback = self._normalize_moc_name(fallback_moc)
        target_file = self.vault_dir / f"{norm_name}.md"
        if not target_file.exists():
            return False

        # 자식 노드 전수 조사 및 안전 대피
        children = self.get_moc_children(norm_name)
        if children:
            self.batch_reassign_nodes(children, norm_fallback)

        # MOC 파일 안전 삭제
        target_file.unlink()
        return True

    def merge_mocs(self, source_moc: str, target_moc: str) -> Dict[str, Any]:
        """
        두 MOC를 하나로 통합 (Merge).
        1. source_moc의 모든 자식 노드를 target_moc로 일괄 이전.
        2. 볼트 내 모든 노드의 [[source_moc]] 링크를 [[target_moc]]로 일괄 치환.
        3. source_moc가 헌법 MOC가 아닐 경우 안전하게 파일 삭제.
        """
        norm_source = self._normalize_moc_name(source_moc)
        norm_target = self._normalize_moc_name(target_moc)

        if norm_source == norm_target:
            raise ValueError("동일한 MOC끼리는 통합할 수 없습니다.")

        if norm_source in CONSTITUTIONAL_MOCS:
            raise PermissionError(f"4대 헌법 MOC({norm_source})는 다른 MOC로 흡수/삭제할 수 없습니다.")

        source_file = self.vault_dir / f"{norm_source}.md"
        target_file = self.vault_dir / f"{norm_target}.md"

        if not target_file.exists():
            raise FileNotFoundError(f"대상 MOC 파일이 존재하지 않습니다: {norm_target}")

        # 1. 자식 노드 이전
        children = self.get_moc_children(norm_source)
        reassign_results = self.batch_reassign_nodes(children, norm_target)

        # 2. 볼트 전체 위키링크 치환 ([[source]] -> [[target]])
        replaced_files_count = 0
        for md_file in self.vault_dir.glob("*.md"):
            if md_file.name == f"{norm_source}.md":
                continue
            try:
                content = md_file.read_text(encoding="utf-8")
                if f"[[{norm_source}]]" in content:
                    updated = content.replace(f"[[{norm_source}]]", f"[[{norm_target}]]")
                    md_file.write_text(updated, encoding="utf-8")
                    replaced_files_count += 1
            except Exception:
                continue

        # 3. 소스 MOC 파일 삭제
        if source_file.exists():
            source_file.unlink()

        return {
            "source_moc": norm_source,
            "target_moc": norm_target,
            "reassigned_children_count": len(children),
            "reassigned_children": children,
            "wikilink_replaced_files_count": replaced_files_count
        }

    def rename_moc(self, old_name: str, new_name: str) -> bool:
        """
        하위 MOC의 이름을 변경하고 볼트 내 모든 참조를 원자적으로 갱신.
        """
        norm_old = self._normalize_moc_name(old_name)
        norm_new = self._normalize_moc_name(new_name)

        if norm_old in CONSTITUTIONAL_MOCS:
            raise PermissionError(f"4대 헌법 MOC({norm_old})는 이름을 변경할 수 없습니다.")

        if not norm_new.startswith("MOC_"):
            norm_new = f"MOC_{norm_new}"

        old_file = self.vault_dir / f"{norm_old}.md"
        new_file = self.vault_dir / f"{norm_new}.md"

        if not old_file.exists():
            raise FileNotFoundError(f"변경할 MOC가 없습니다: {norm_old}")
        if new_file.exists():
            raise FileExistsError(f"이미 존재하는 MOC 이름입니다: {norm_new}")

        # 파일명 변경
        old_file.rename(new_file)

        # 내용 내부 타이틀 변경
        content = new_file.read_text(encoding="utf-8")
        content = content.replace(f"# {norm_old}", f"# {norm_new}")
        new_file.write_text(content, encoding="utf-8")

        # 볼트 전체 위키링크 및 프론트매터 갱신
        for md_file in self.vault_dir.glob("*.md"):
            try:
                c = md_file.read_text(encoding="utf-8")
                if f"[[{norm_old}]]" in c:
                    c = c.replace(f"[[{norm_old}]]", f"[[{norm_new}]]")
                    md_file.write_text(c, encoding="utf-8")
            except Exception:
                continue

        return True
