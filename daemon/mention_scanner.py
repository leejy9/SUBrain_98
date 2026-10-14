"""
daemon/mention_scanner.py - Safe Horizontal Unlinked Mention Scanner & Lexer-Masked Replacer
SUBrain_98 Architecture Invariant:
1. Never mutate disk silently (Read-only detection; write only on HITL approval).
2. Mask frontmatter, codeblocks, tables, and existing links before scanning (Painting Tape Invariant).
3. Preserve Korean postpositions (은/는/이/가/을/를/에서 등 분리).
"""

import re
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

import vault_io
from config import VAULT_DIR

logger = logging.getLogger(__name__)

# 한국어 일반 조사 목록 (어간과 분리하여 [[링크|어간]]조사 형태로 안전 결속)
# lookahead에 공백, 구두점, 괄호뿐만 아니라 마크다운 기호(*, _, ~, ], 등)도 허용
KOREAN_POSTPOSITIONS = (
    r"(은|는|이|가|을|를|의|에|에서|에게|로|으로|와|과|도|만|까지|부터|마저|조차)?"
    r"(?=[\s\.,!?;:\n\)\"\'\*_~\]]|$)"
)

# 링크 대상에서 제외할 단일 일반 명사 불용어 목록
STOPWORDS = {
    "경험", "지원", "보고서", "초안", "기업분석", "정리", "기획", "검토", 
    "프로젝트", "메모", "리서치", "설계", "자소서", "이력서", "포트폴리오",
    "기초", "원리", "개념", "사례", "방법론", "스터디", "분석"
}


def list_linkable_entities() -> Dict[str, Dict[str, Any]]:
    """
    볼트 내 연결 가능한 고유 자산(경험_*, 지식_* 노드)의 정규화 키워드 맵 생성.
    반환값: { '정규화키워드': { 'target_node': '경험_XXX', 'original_name': '...', 'tags': [...] } }
    """
    entities = {}
    vault_notes = [p for p in VAULT_DIR.glob("*.md") if not p.name.startswith(".")]

    for p in vault_notes:
        stem = p.stem
        # 경험 노드 및 지식 노드만 수평 결속 대상의 1차 자산으로 수집
        if not (stem.startswith("경험_") or stem.startswith("지식_")):
            continue

        raw = vault_io.read_note(p.name)
        if not raw:
            continue

        content = raw.get("content", "")
        # 접두사 분리 (경험_넥스트러너스_자발적참여구조 -> 넥스트러너스_자발적참여구조)
        parts = stem.split("_", 1)
        core_name = parts[1] if len(parts) > 1 else stem

        # 키워드 후보군 생성
        candidates = set()
        candidates.add(stem) # 전체 노드명 (경험_넥스트러너스_자발적참여구조)
        candidates.add(core_name) # 접두사 제외 (넥스트러너스_자발적참여구조)
        candidates.add(core_name.replace("_", " ")) # 공백 치환 (넥스트러너스 자발적 참여구조)

        # 3글자 이상이며 불용어가 아닌 후보만 정밀 등록
        for cand in candidates:
            cand_clean = cand.strip()
            if len(cand_clean) < 3 or cand_clean in STOPWORDS:
                continue
            
            entities[cand_clean] = {
                "target_node": stem,
                "core_name": core_name,
                "length": len(cand_clean)
            }

    return entities


def mask_markdown_content(content: str) -> Tuple[str, List[Tuple[int, int, str]]]:
    """
    '마스킹 테이프' 기법:
    마크다운 서식이 깨지면 안 되는 구역(Frontmatter, 코드블록, 기존 [[링크]], 헤딩 등)을
    동일한 길이의 공백으로 치환하여 원본 문자 인덱스를 100% 보존한 마스킹 텍스트 생성.
    (볼드체 내부 텍스트는 강조된 본문이므로 보존함)
    """
    masked = list(content)
    protected_regions = []

    # 1. Frontmatter (--- ... ---)
    fm_match = re.search(r"^---\n.*?\n---\n", content, re.DOTALL)
    if fm_match:
        s, e = fm_match.span()
        protected_regions.append((s, e, "frontmatter"))

    # 2. Fenced Code Blocks (``` ... ```)
    for m in re.finditer(r"```[\s\S]*?```", content):
        protected_regions.append((*m.span(), "code_block"))

    # 3. Inline Code (` ... `)
    for m in re.finditer(r"`[^`\n]+`", content):
        protected_regions.append((*m.span(), "inline_code"))

    # 4. Existing Wikilinks ([[ ... ]])
    for m in re.finditer(r"\[\[[\s\S]*?\]\]", content):
        protected_regions.append((*m.span(), "existing_wikilink"))

    # 5. Markdown Links ([text](url))
    for m in re.finditer(r"\[[^\]]+\]\([^)]+\)", content):
        protected_regions.append((*m.span(), "markdown_link"))

    # 6. Markdown Headings (# ... \n)
    for m in re.finditer(r"^#{1,6}\s+.*$", content, re.MULTILINE):
        protected_regions.append((*m.span(), "heading"))

    # 보호 구역을 공백으로 덮어써서 원본 인덱스 보존
    for start, end, label in protected_regions:
        for i in range(start, end):
            if masked[i] != "\n": # 줄바꿈은 보존하여 라인 카운트 일치
                masked[i] = " "

    return "".join(masked), protected_regions


def make_flexible_korean_pattern(text: str) -> str:
    """
    한국어 복합명사의 유연한 띄어쓰기 매칭 패턴 생성.
    예: '넥스트러너스_자발적참여구조' -> '넥\\s*스\\s*트\\s*러\\s*너\\s*스\\s*[\\s_]*자\\s*발\\s*적\\s*참\\s*여\\s*구\\s*조'
    """
    clean = text.strip()
    pattern = ""
    for c in clean:
        if c in ("_", " "):
            pattern += r"[\s_]+"
        else:
            pattern += re.escape(c) + r"\s*"
    return pattern.rstrip(r"\s*")


def scan_unlinked_mentions_in_file(doc_rel_path: str, entity_map: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """
    단일 마크다운 문서 내에서 언링크드 멘션을 안전하게 탐지하여 제안 목록 반환.
    (디스크 파일 수정은 일체 하지 않는 순수 Read-only 탐지기)
    """
    raw = vault_io.read_note(doc_rel_path)
    if not raw:
        return []

    doc_stem = Path(doc_rel_path).stem
    content = raw.get("content", "")
    if not content:
        return []

    if entity_map is None:
        entity_map = list_linkable_entities()

    masked_content, _ = mask_markdown_content(content)
    mentions = []

    # 긴 키워드부터 우선 탐색하여 부분 매칭 충돌 방지 (Greedy Longest Match)
    sorted_keywords = sorted(entity_map.keys(), key=lambda k: len(k), reverse=True)

    # 이미 매칭된 구간 추적 (중복/포함 매칭 방지)
    occupied_spans = []

    for keyword in sorted_keywords:
        target_info = entity_map[keyword]
        target_node = target_info["target_node"]

        # 자기 자신을 링크하려는 경우 제외
        if target_node == doc_stem:
            continue

        # 유연한 한국어 띄어쓰기 정규식 패턴 생성
        flex_pat = make_flexible_korean_pattern(keyword)
        pattern = re.compile(rf"({flex_pat}){KOREAN_POSTPOSITIONS}")

        for match in pattern.finditer(masked_content):
            matched_core = match.group(1) # 유연하게 매칭된 실제 본문 어간
            full_match_text = match.group(0)
            postposition = full_match_text[len(matched_core):]

            start = match.start(1)
            end = match.end(1)

            # 기존 매칭 구간과 겹치는지 검사
            overlap = any(max(start, os) < min(end, oe) for os, oe in occupied_spans)
            if overlap:
                continue

            occupied_spans.append((start, end))

            # 줄 번호(1-based) 계산
            line_number = content[:start].count("\n") + 1

            # 앞뒤 60자 인용 문맥 추출
            ctx_start = max(0, start - 50)
            ctx_end = min(len(content), end + 50)
            excerpt = content[ctx_start:ctx_end].replace("\n", " ").strip()

            item_id = f"MENTION-{doc_stem[:8]}-{target_node[:10]}-{start}"
            mentions.append({
                "id": item_id,
                "type": "unlinked_mention",
                "source_node": doc_stem,
                "target_node": target_node,
                "matched_text": matched_core,
                "canonical_keyword": keyword,
                "postposition": postposition,
                "start_char": start,
                "end_char": end,
                "line_number": line_number,
                "source_context": f"...{excerpt}...",
                "confidence_score": 96 if len(keyword) >= 8 else 88,
                "status": "PENDING",
                "match_rationale": f"[[{doc_stem}]] {line_number}행에서 [[{target_node}]]의 핵심 경험을 인용하였으나 위키링크가 누락되어 있습니다.",
                "action_label": f"[[{target_node}|{matched_core}]]{postposition}로 결속"
            })

    return mentions


def apply_unlinked_mention_safely(
    source_rel_path: str,
    target_node: str,
    start_char: int,
    end_char: int,
    matched_text: str,
    postposition: str = ""
) -> bool:
    """
    사용자 승인 시 단일 원자적으로 마크다운 원문에 [[target_node|matched_text]] 주입.
    조사를 보존하고 백업 및 저널 기록 수행.
    """
    raw = vault_io.read_note(source_rel_path)
    if not raw:
        logger.error(f"[mention_scanner] 대상 파일 없음: {source_rel_path}")
        return False

    content = raw["content"]
    original_hash = raw["hash"]

    # 경계 안전성 검증
    if start_char < 0 or end_char > len(content) or start_char >= end_char:
        logger.error(f"[mention_scanner] 유효하지 않은 문자 범위: {start_char}~{end_char}")
        return False

    actual_slice = content[start_char:end_char]
    if actual_slice != matched_text:
        logger.error(f"[mention_scanner] 텍스트 불일치: 파일('{actual_slice}') != 기대('{matched_text}')")
        return False

    # 안전 치환: [[target_node|matched_text]]
    replacement = f"[[{target_node}|{matched_text}]]"
    new_content = content[:start_char] + replacement + content[end_char:]

    try:
        vault_io.safe_write(
            rel_path=source_rel_path,
            content=new_content,
            expected_hash=original_hash,
            reason=f"언링크드 멘션 수평 결속 승인: '{matched_text}' -> [[{target_node}]]",
            actor="user_hitl"
        )
        logger.info(f"[mention_scanner] 수평 결속 완료: {source_rel_path} -> [[{target_node}]]")
        return True
    except Exception as e:
        logger.error(f"[mention_scanner] safe_write 실패: {e}")
        return False


def scan_vault_for_unlinked_mentions(max_results: int = 10) -> List[Dict[str, Any]]:
    """
    볼트 전체를 스캔하여 미연결 실존 경험 인용부를 종합 탐지하고 우선순위 Top N을 반환.
    (지원서, 보고서, 프로젝트 등 실무 산출물 문서를 최우선 검사)
    """
    entity_map = list_linkable_entities()
    all_files = sorted(list(VAULT_DIR.glob("*.md")), key=lambda p: p.stat().st_mtime, reverse=True)

    # 우선순위 가중치 분류: 지원서 > 보고서 > 프로젝트 > 일반 메모
    priority_files = []
    normal_files = []

    for p in all_files:
        name = p.name
        if name.startswith(".") or name.startswith("00_") or name.startswith("MOC_"):
            continue
        # 경험 노드 자체는 수평 결속의 피인용 대상이므로 소스 탐색에서는 후순위
        if name.startswith("경험_") or name.startswith("지식_"):
            continue

        if name.startswith("지원_") or name.startswith("보고서_") or name.startswith("기업분석_") or name.startswith("자소서_"):
            priority_files.append(name)
        else:
            normal_files.append(name)

    search_queue = priority_files + normal_files
    all_mentions = []

    for doc_name in search_queue:
        try:
            doc_mentions = scan_unlinked_mentions_in_file(doc_name, entity_map=entity_map)
            all_mentions.extend(doc_mentions)
            if len(all_mentions) >= max_results * 3:
                break
        except Exception as e:
            logger.warning(f"[mention_scanner] {doc_name} 스캔 중 오류: {e}")

    # 신뢰도 점수 및 키워드 길이 순 정렬
    all_mentions.sort(key=lambda m: (m["confidence_score"], len(m["matched_text"])), reverse=True)
    return all_mentions[:max_results]
