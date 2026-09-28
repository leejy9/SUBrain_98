import re
from pathlib import Path
from typing import List, Dict, Any, Optional
from config import VAULT_DIR, CONSTITUTION_FILE

class VaultIndexer:
    def __init__(self, vault_dir: Path = VAULT_DIR, constitution_path: Path = CONSTITUTION_FILE):
        self.vault_dir = vault_dir
        self.constitution_path = constitution_path

    def get_constitution(self) -> str:
        """00_헌법.md 파일의 전체 텍스트를 반환합니다."""
        if self.constitution_path.exists():
            return self.constitution_path.read_text(encoding="utf-8")
        return "헌법 파일이 없습니다. 기본 원자화, 링크 이유 기재, 고립 금지 원칙을 적용하세요."

    def get_module(self, module_name: str) -> str:
        """지정된 모듈 파일의 텍스트를 반환합니다."""
        if not module_name.endswith(".md"):
            module_name += ".md"
        direct_path = self.vault_dir / module_name
        if direct_path.exists():
            return direct_path.read_text(encoding="utf-8")
        for found in self.vault_dir.rglob(module_name):
            return found.read_text(encoding="utf-8")
        return ""

    def list_notes(self) -> List[Dict[str, Any]]:
        """Vault 내의 모든 마크다운 파일의 메타데이터 요약을 추출합니다."""
        notes = []
        if not self.vault_dir.exists():
            return notes

        # .md 파일 탐색 (하위 폴더 포함하되 숨김 폴더 제외)
        for path in self.vault_dir.rglob("*.md"):
            if any(part.startswith(".") for part in path.parts):
                continue
            if path.name == "00_헌법.md":
                continue

            name = path.stem
            try:
                content = path.read_text(encoding="utf-8")
            except Exception:
                continue

            # 기본 프론트매터 및 H1 추출
            tags = re.findall(r'#([a-zA-Z0-9_\-\/가-힣]+)', content)
            h1_match = re.search(r'^#\s+(.+)$', content, re.MULTILINE)
            h1 = h1_match.group(1).strip() if h1_match else name

            # 분류 유형 태깅
            note_category = "일반"
            if name.startswith("경험_"):
                note_category = "경험"
            elif name.startswith("역량_"):
                note_category = "역량"
            elif name.startswith("프로젝트_"):
                note_category = "프로젝트"
            elif name.startswith("성과_"):
                note_category = "성과"
            elif name.startswith("개념_"):
                note_category = "개념"
            elif name.startswith("지원_"):
                note_category = "지원서"

            # 연결된 위키링크 추출
            outgoing_links = re.findall(r'\[\[(.*?)\]\]', content)

            notes.append({
                "name": name,
                "h1": h1,
                "category": note_category,
                "path": str(path.relative_to(self.vault_dir)),
                "full_path": path,
                "snippet": content[:300].replace("\n", " "),
                "outgoing_links": outgoing_links
            })

        return notes

    def get_note_detail(self, node_name: str) -> Optional[Dict[str, Any]]:
        """특정 노드의 상세 본문 및 1-hop 이웃 링크를 인출합니다."""
        clean_name = re.sub(r'\[\[|\]\]', '', node_name).strip()
        # 확장자 제거
        if clean_name.endswith('.md'):
            clean_name = clean_name[:-3]

        for path in self.vault_dir.rglob(f"{clean_name}.md"):
            try:
                content = path.read_text(encoding="utf-8")
                outgoing_links = re.findall(r'\[\[(.*?)\]\]', content)
                h1_match = re.search(r'^#\s+(.+)$', content, re.MULTILINE)
                h1 = h1_match.group(1).strip() if h1_match else clean_name
                return {
                    "name": clean_name,
                    "h1": h1,
                    "content": content,
                    "outgoing_links": outgoing_links,
                    "path": str(path.relative_to(self.vault_dir))
                }
            except Exception:
                continue
        return None

    def get_context_for_prompt(self, max_items: int = 50) -> str:
        """LLM 프롬프트에 제공할 기존 지식 베이스의 노드 요약 목록을 생성합니다."""
        notes = self.list_notes()
        if not notes:
            return "현재 볼트에 등록된 기존 노트가 없습니다."

        lines = ["### 기존 볼트 내 노드 목록 (연결 후보군):"]
        priority = sorted(notes, key=lambda x: (x["category"] not in ["역량", "프로젝트", "경험"], x["name"]))
        for n in priority[:max_items]:
            lines.append(f"- [[{n['name']}]] ({n['category']}) : {n['h1']}")

        return "\n".join(lines)
