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
            if name.startswith("MOC_") or "MOC" in name or name.endswith("_MOC"):
                note_category = "MOC"
            elif name == "00_헌법":
                note_category = "헌법"
            elif name.startswith("경험_"):
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

            # YAML Frontmatter 제거 후 마크다운 본문 추출 (줄바꿈 보존)
            clean_body = re.sub(r'^---\s*[\s\S]*?---\s*', '', content).strip()
            markdown_snippet = clean_body[:700] if clean_body else content[:300]

            notes.append({
                "name": name,
                "h1": h1,
                "category": note_category,
                "path": str(path.relative_to(self.vault_dir)),
                "full_path": path,
                "snippet": markdown_snippet,
                "outgoing_links": outgoing_links,
                "mtime": path.stat().st_mtime
            })

        return notes

    def get_graph_data(self) -> Dict[str, Any]:
        """D3.js Force Graph에 전달할 정규화된 노드 및 엣지 네트워크 구조를 생성합니다."""
        import datetime
        notes = self.list_notes()
        now_ts = datetime.datetime.now().timestamp()

        node_map = {}
        inbound_counts = {}

        # 1. 노드 정규화
        for n in notes:
            name = n["name"]
            mtime = n.get("mtime", now_ts)
            age_days = max(0.0, (now_ts - mtime) / 86400.0)
            is_new = age_days <= 1.0  # 24시간 이내

            if is_new:
                age_group = "new"
            elif age_days <= 7.0:
                age_group = "recent"
            elif age_days <= 30.0:
                age_group = "medium"
            else:
                age_group = "old"

            # 카테고리 세분화
            cat = n["category"]
            if name.startswith("MOC_") or "MOC" in name or name.endswith("_MOC"):
                cat = "MOC"
            elif name == "00_헌법":
                cat = "헌법"
            elif name.startswith("템플릿_"):
                cat = "템플릿"

            node_map[name] = {
                "id": name,
                "name": name,
                "h1": n["h1"],
                "category": cat,
                "path": n["path"],
                "age_days": round(age_days, 1),
                "is_new": is_new,
                "age_group": age_group,
                "outgoing_links": n["outgoing_links"],
                "snippet": n["snippet"],
                "referenced_count": 1,
            }
            inbound_counts[name] = 0

        # 2. 엣지 연결 및 인바운드 집계
        raw_links = []
        for n in notes:
            src = n["name"]
            for target_raw in n["outgoing_links"]:
                # [[링크명|별칭]] 형태 정제
                target = target_raw.split("|")[0].strip()
                if target.endswith(".md"):
                    target = target[:-3]
                if target.startswith("[[") and target.endswith("]]"):
                    target = target[2:-2]

                if not target or target == src:
                    continue

                # 볼트에 실재하지 않더라도 MOC_로 시작하는 핵심 허브인 경우 자동 등록
                if target.startswith("MOC_") and target not in node_map:
                    node_map[target] = {
                        "id": target,
                        "name": target,
                        "h1": f"{target} (지식 지도)",
                        "category": "MOC",
                        "path": f"{target}.md",
                        "age_days": 1.0,
                        "is_new": False,
                        "age_group": "recent",
                        "outgoing_links": [],
                        "snippet": f"{target} MOC 중심 허브입니다. 수많은 실전 경험과 지식 노드를 통합 연결합니다.",
                        "referenced_count": 1,
                    }
                    inbound_counts[target] = 0

                # 볼트에 실재하는 노드 대상만 링크 등록
                if target in node_map:
                    raw_links.append({"source": src, "target": target})
                    inbound_counts[target] = inbound_counts.get(target, 0) + 1

        # 3. 노드 참조 가중치(referenced_count) 업데이트
        for name, node in node_map.items():
            inbound = inbound_counts.get(name, 0)
            node["inbound_count"] = inbound
            node["referenced_count"] = max(1, inbound)

        # 4. 중복 엣지 제거 (무방향 쌍 유일성 확보)
        seen_edges = set()
        deduped_links = []
        for link in raw_links:
            edge_key = tuple(sorted([link["source"], link["target"]]))
            if edge_key not in seen_edges:
                seen_edges.add(edge_key)
                deduped_links.append(link)

        nodes_list = list(node_map.values())
        return {
            "nodes": nodes_list,
            "links": deduped_links,
            "total_nodes": len(nodes_list),
            "total_links": len(deduped_links),
            "new_nodes_count": sum(1 for n in nodes_list if n["is_new"])
        }

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
