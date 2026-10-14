import re
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple
try:
    from config import VAULT_DIR
except ImportError:
    from daemon.config import VAULT_DIR

class TagRegistry:
    """
    Subrain_98 통제 태그 사전 (Controlled Tag Lexicon) 레지스트리.
    Ground Truth: 볼트 내 '00_태그사전.md'
    기능: 공식 표준 태그 로드, 동의어/유의어 매핑, 정규화(Canonicalization), 신규 발의(Proposal).
    """

    def __init__(self, tag_dict_path: Optional[Path] = None):
        self.tag_dict_path = tag_dict_path or (VAULT_DIR / "00_태그사전.md")
        self.canonical_tags: Set[str] = set()
        self.synonym_map: Dict[str, str] = {}  # synonym -> canonical_tag
        self.tag_definitions: Dict[str, str] = {}  # canonical_tag -> description
        self.tag_categories: Dict[str, str] = {}  # canonical_tag -> category
        self.synonyms_by_tag: Dict[str, List[str]] = {}  # canonical_tag -> list of synonyms
        self.load_from_vault()

    def clean_tag_name(self, tag: str) -> str:
        """태그명에서 '#' 기호 및 공백 정리"""
        return tag.strip().lstrip("#").strip()

    def load_from_vault(self) -> None:
        """볼트의 00_태그사전.md를 파싱하여 인덱스를 빌드"""
        if not self.tag_dict_path.exists():
            return

        content = self.tag_dict_path.read_text(encoding="utf-8")
        current_category = "일반"

        lines = content.splitlines()
        for i, line in enumerate(lines):
            line_str = line.strip()
            if line_str.startswith("## 1."):
                current_category = "역량"
            elif line_str.startswith("## 2."):
                current_category = "상황"
            elif line_str.startswith("## 3."):
                current_category = "도메인"

            # 표준 태그 파싱: - **#역량/데이터기반의사결정**: 설명
            match = re.search(r"-\s+\*\*#?([^\*:]+)\*\*:\s*(.*)", line_str)
            if match:
                raw_tag = match.group(1).strip()
                desc = match.group(2).strip()

                # '#' 접두사 표준화
                canon_tag = f"#{raw_tag}" if not raw_tag.startswith("#") else raw_tag
                self.canonical_tags.add(canon_tag)
                self.tag_definitions[canon_tag] = desc
                self.tag_categories[canon_tag] = current_category
                if canon_tag not in self.synonyms_by_tag:
                    self.synonyms_by_tag[canon_tag] = []

                # 자기 자신(축약형 포함)도 매핑
                short_name = canon_tag.split("/")[-1]
                self.synonym_map[self.clean_tag_name(canon_tag)] = canon_tag
                self.synonym_map[short_name] = canon_tag

                # 다음 줄이나 본문에서 유의어 매핑 확인: 동의어/유의어 매핑: [A, B, C]
                check_lines = [line_str]
                if i + 1 < len(lines):
                    check_lines.append(lines[i + 1].strip())

                for c_line in check_lines:
                    syn_match = re.search(r"동의어/유의어 매핑:\s*\[(.*?)\]", c_line)
                    if syn_match:
                        raw_syns = syn_match.group(1).split(",")
                        for s in raw_syns:
                            clean_s = self.clean_tag_name(s)
                            if clean_s:
                                self.synonym_map[clean_s] = canon_tag
                                if clean_s not in self.synonyms_by_tag[canon_tag] and clean_s != self.clean_tag_name(canon_tag) and clean_s != short_name:
                                    self.synonyms_by_tag[canon_tag].append(clean_s)

    def add_synonym(self, canonical_tag: str, new_synonym: str) -> bool:
        """볼트 내 00_태그사전.md에 동의어를 영구 추가하고 레지스트리 핫리로드"""
        clean_syn = self.clean_tag_name(new_synonym)
        if not clean_syn:
            return False

        canon = f"#{canonical_tag.lstrip('#')}"
        if not self.tag_dict_path.exists():
            return False

        content = self.tag_dict_path.read_text(encoding="utf-8")
        lines = content.splitlines()
        new_lines = []
        found_tag = False
        added = False

        for i, line in enumerate(lines):
            new_lines.append(line)
            # - **#역량/문제해결**: ...
            if canon in line and ("**" in line or line.strip().startswith("-")):
                found_tag = True
                continue

            if found_tag and not added:
                if "동의어/유의어 매핑:" in line:
                    # 기존 매핑 줄에 추가
                    match = re.search(r"(동의어/유의어 매핑:\s*\[)(.*?)(\])", line)
                    if match:
                        existing = [s.strip() for s in match.group(2).split(",") if s.strip()]
                        if f"#{clean_syn}" not in existing and clean_syn not in existing:
                            existing.append(f"#{clean_syn}")
                            new_line = f"    - 동의어/유의어 매핑: [{', '.join(existing)}]"
                            new_lines[-1] = new_line
                            added = True
                elif line.strip().startswith("- **") or line.strip().startswith("## "):
                    # 다음 태그나 섹션이 나왔는데 동의어 줄이 없었던 경우 이전 줄 뒤에 삽입
                    new_lines.insert(-1, f"    - 동의어/유의어 매핑: [#{clean_syn}]")
                    added = True
                    found_tag = False

        if found_tag and not added:
            new_lines.append(f"    - 동의어/유의어 매핑: [#{clean_syn}]")
            added = True

        if added:
            self.tag_dict_path.write_text("\n".join(new_lines), encoding="utf-8")
            self.load_from_vault()
            return True
        return False

    def canonicalize(self, raw_tag: str) -> Tuple[str, bool]:
        """
        입력된 임의의 태그를 공식 표준 태그로 정규화.
        반환: (표준태그, 매핑성공여부)
        """
        clean_name = self.clean_tag_name(raw_tag)
        short_name = clean_name.split("/")[-1]

        # 1. 완전 일치 (동의어 맵)
        if clean_name in self.synonym_map:
            return self.synonym_map[clean_name], True

        # 2. 짧은 이름 일치
        if short_name in self.synonym_map:
            return self.synonym_map[short_name], True

        # 3. 공식 태그 직접 일치
        formatted = f"#{clean_name}"
        if formatted in self.canonical_tags:
            return formatted, True

        # 4. 축약 태그에 카테고리 접두사를 붙여 매칭 시도
        for cat in ["역량", "상황", "도메인"]:
            candidate = f"#{cat}/{clean_name}"
            if candidate in self.canonical_tags:
                return candidate, True

        # 사전에 없는 자유 태그
        return formatted if not formatted.startswith("#") else raw_tag, False

    def canonicalize_list(self, raw_tags: List[str]) -> Tuple[List[str], List[str]]:
        """
        태그 리스트를 일괄 정규화하고 정규화된 태그와 미등재 태그를 분리.
        반환: (정규화된_태그_리스트, 미등재_태그_리스트)
        """
        canonical_result: List[str] = []
        unmapped: List[str] = []
        seen: Set[str] = set()

        for t in raw_tags:
            canon, is_mapped = self.canonicalize(t)
            if is_mapped:
                if canon not in seen:
                    canonical_result.append(canon)
                    seen.add(canon)
            else:
                unmapped.append(t)

        return canonical_result, unmapped

    def get_allowed_tags_summary(self) -> str:
        """LLM 프롬프트에 제공할 통제 사전 요약"""
        summary_lines = ["[공식 통제 태그 사전 (00_태그사전.md 기준)]"]
        for cat in ["역량", "상황", "도메인"]:
            tags = [t for t, c in self.tag_categories.items() if c == cat]
            if tags:
                tag_strs = [f"{t} ({self.tag_definitions.get(t, '')})" for t in tags]
                summary_lines.append(f"- [{cat}]: " + " | ".join(tag_strs))
        summary_lines.append("※ 지침: 신규 태그를 자의적으로 만들지 말고 위 공식 태그로 정규화하십시오.")
        return "\n".join(summary_lines)

    def propose_new_tag(self, raw_tag: str, category: str, rationale: str) -> Dict[str, str]:
        """사전에 없는 신규 태그에 대한 인간 승인용 발의(Proposal) 객체 생성"""
        clean_name = self.clean_tag_name(raw_tag)
        proposed_tag = f"#{category}/{clean_name}" if not clean_name.startswith(f"{category}/") else f"#{clean_name}"
        return {
            "type": "tag_proposal",
            "proposed_tag": proposed_tag,
            "category": category,
            "raw_input": raw_tag,
            "rationale": rationale,
            "status": "pending_hitl_approval"
        }
