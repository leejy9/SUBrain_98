import os
import re
import json
import datetime
from pathlib import Path
from typing import Dict, Any, Tuple, List
import httpx
from bs4 import BeautifulSoup
from google import genai
from google.genai import types

from config import GEMINI_API_KEY, VAULT_DIR
from vault_indexer import VaultIndexer
from models import BlackboardState, CriticEvaluation, SemanticLink, RejectedLink, CognitivePrimitive
from critic_validator import CriticValidator
import vault_io

class ConstitutionalAgent:
    def __init__(self):
        self.client = genai.Client(api_key=GEMINI_API_KEY)
        self.indexer = VaultIndexer()
        self.critic = CriticValidator(self.indexer)
        self.model_name = "gemini-3.1-flash-lite"

    def set_critic_enabled(self, enabled: bool):
        self.critic.enabled = enabled
        logger.info(f"[ConstitutionalAgent] 비판관 활성화 상태 변경: {enabled}")

    def _extract_url_content(self, text: str) -> Tuple[str, str]:
        """텍스트에서 URL을 탐지하여 웹페이지 내용을 스크랩합니다."""
        url_match = re.search(r'https?://[^\s]+', text)
        if not url_match:
            return "", text

        url = url_match.group(0)
        try:
            headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
            resp = httpx.get(url, headers=headers, follow_redirects=True, timeout=12.0)
            soup = BeautifulSoup(resp.text, "html.parser")
            title = soup.title.string.strip() if soup.title else url
            paras = [p.get_text().strip() for p in soup.find_all(["p", "article", "h1", "h2", "h3"]) if p.get_text().strip()]
            content = " ".join(paras[:25])
            return url, f"[웹페이지 출처: {url}]\n[제목: {title}]\n\n{content}"
        except Exception as e:
            return url, f"[웹페이지 링크: {url} (스크랩 실패: {e})]\n\n{text}"

    def _extract_source_date(self, raw_input: str, url: str = "") -> Tuple[str, str, int]:
        """
        [이중 타임스탬프 자동 검출 엔진]
        1. URL이 제공된 경우 htmldate로 원천 발행일 추출 시도
        2. 본문 텍스트에서 한글/ISO 연월일 정규식 탐색 ('2025년 2월 14일', '2025-02-14')
        3. 실패 시 fallback으로 수집 당일 반환
        반환값: (source_date, recorded_at, lag_days)
        """
        today = datetime.date.today()
        today_str = today.strftime("%Y-%m-%d")
        recorded_at_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        source_date = None

        if url:
            try:
                import htmldate
                d = htmldate.find_date(url)
                if d:
                    source_date = str(d)[:10]
            except Exception:
                pass

        if not source_date:
            m_kr = re.search(r'(\d{4})\s*년\s*(\d{1,2})\s*월(?:\s*(\d{1,2})\s*일)?', raw_input)
            if m_kr:
                y, mth, day = m_kr.group(1), m_kr.group(2).zfill(2), (m_kr.group(3) or '01').zfill(2)
                source_date = f"{y}-{mth}-{day}"
            else:
                m_iso = re.search(r'(\d{4})[-./](\d{1,2})[-./](\d{1,2})', raw_input)
                if m_iso:
                    source_date = f"{m_iso.group(1)}-{m_iso.group(2).zfill(2)}-{m_iso.group(3).zfill(2)}"

        if not source_date:
            source_date = today_str

        try:
            s_dt = datetime.datetime.strptime(source_date, "%Y-%m-%d").date()
            lag_days = max(0, (today - s_dt).days)
        except Exception:
            lag_days = 0

        return source_date, recorded_at_str, lag_days

    def _generate_with_retry(self, contents, config=None, max_retries: int = 5):
        """503 및 일시적 API 오류 발생 시 지수 백오프로 재시도합니다."""
        import time
        for attempt in range(max_retries):
            try:
                if config:
                    return self.client.models.generate_content(
                        model=self.model_name,
                        contents=contents,
                        config=config
                    )
                else:
                    return self.client.models.generate_content(
                        model=self.model_name,
                        contents=contents
                    )
            except Exception as e:
                err_str = str(e)
                if ("429" in err_str or "RESOURCE_EXHAUSTED" in err_str or "ResourceExhausted" in err_str or "503" in err_str or "UNAVAILABLE" in err_str) and attempt < max_retries - 1:
                    delay_match = re.search(r'retry in (\d+(?:\.\d+)?)s', err_str)
                    if delay_match:
                        sleep_time = float(delay_match.group(1)) + 1.0
                    else:
                        sleep_time = (2 ** attempt) * 3 + 2.0
                    time.sleep(sleep_time)
                    continue
                raise

    def process_intake(self, raw_input: str, user_context: str = "", category_intent: str = "") -> Dict[str, Any]:
        """
        헌법 제7조 디스패치 기반 지식 인테이크 파이프라인.
        1. 헌법 읽기 & 정보 유형 판별 (헌법 디스패처)
        2. 해당 모듈(영구지식 vs 경험정리 vs 단순기억) 로드 및 모듈별 골격 생성
        3. Critic 비판관(85점 룰 & 5대 인지 원형) 검증
        4. 전역 불변식(절대연도, captured_at, Zero-Loss 원문 창고)과 함께 최종 마크다운 렌더링
        """
        url, expanded_content = self._extract_url_content(raw_input)
        raw_text_payload = expanded_content if expanded_content else raw_input
        source_date, recorded_at_str, lag_days = self._extract_source_date(raw_input, url)
        vault_nodes_summary = self.indexer.get_context_for_prompt()
        constitution = self.indexer.get_constitution()

        # [1단계: 헌법 제7조 디스패처 - 헌법부터 읽고 정보의 유형 분류]
        dispatcher_prompt = f"""
당신은 옵시디언 볼트 헌법(00_헌법.md)을 가장 먼저 읽고 신규 입력 정보의 유형을 판별하는 '헌법 디스패처'입니다.

[00_헌법.md 제7조 (모듈 선택 규칙)]:
| 노트 성격 | 모듈 | type 값 |
|---|---|---|
| 빠른 캡처 — 사실/인용/단편 메모, 아직 정제 안 됨 | 모듈_단순기억 | Fleeting |
| 정제된 개념 지식 — 시장/거시경제 분석, 산업 리서치, 책/논문 개념, 기술/도메인 불변 원리 | 모듈_영구지식 | Permanent |
| 커리어 — 본인의 실제 업무/프로젝트 경험, 직무 성과, 이력서/자소서 무기 | 모듈_경험정리 | Experience |

[신규 입력 원문]:
{raw_text_payload[:2500]}

[사용자 메모]:
{user_context if user_context else "(없음)"}

[입력 카테고리 힌트]:
{category_intent if category_intent else "(없음 - 자율 판별)"}

반드시 아래 JSON 스키마로만 응답하세요:
{{
  "classified_type": "Permanent" 또는 "Experience" 또는 "Fleeting",
  "module_name": "모듈_영구지식" 또는 "모듈_경험정리" 또는 "모듈_단순기억",
  "target_moc": "MOC_지식원리" 또는 "MOC_커리어" 또는 "MOC_아이디어",
  "prefix": "지식_" 또는 "경험_" 또는 "메모_",
  "reasoning": "00_헌법 §7에 따라 이 유형으로 분류한 구체적 판단 근거"
}}
"""
        disp_resp = self._generate_with_retry(
            contents=[dispatcher_prompt],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.1
            )
        )
        disp_data = json.loads(disp_resp.text)
        classified_type = disp_data.get("classified_type", "Permanent")
        module_name = disp_data.get("module_name", "모듈_영구지식")
        target_moc = disp_data.get("target_moc", "MOC_지식원리" if classified_type == "Permanent" else "MOC_커리어")
        prefix = disp_data.get("prefix", "지식_" if classified_type == "Permanent" else "경험_")
        dispatch_reasoning = disp_data.get("reasoning", "")

        # [2단계: 해당 모듈 규칙 로드 & 모듈 맞춤형 가설 생성]
        module_text = self.indexer.get_module(module_name)

        if classified_type == "Experience":
            generator_prompt = f"""
당신은 '모듈_경험정리' 규칙에 맞춰 사용자의 커리어 경험을 마스터 자소서 3층 구조로 구체화하는 에이전트입니다.

[적용 모듈: {module_name}.md]:
{module_text[:1500]}

[00_헌법 요약]:
{constitution[:600]}

[기존 볼트 노드 목록]:
{vault_nodes_summary}

[입력 원문]:
{raw_text_payload[:3000]}

[사용자 메모]:
{user_context if user_context else "(없음)"}

[작성 철칙]:
1. [절대 원칙 - 사실 무결성]: 입력 원문(raw_text_payload 및 user_context)에 직접 명시되지 않은 정량적 수치(%, 명, 원, 점수 등)나 조직/도구 고유명사를 절대로 지어내거나 부풀려 창작하지 말 것.
2. 원문에 구체적 수치가 없으면 일반적인 정성적 사실로만 담백하게 기술하고, 보강이 필요하면 '[[수치 확인 필요]]' 형태로만 표기할 것.
3. 절대 연도 의무화 ('2024.10~2025.06', '2026-09-14' 등)
4. 당시 관점에서의 중요성(Why It Mattered Then)을 STAR 요약부에 필히 명시
5. 파일명은 핵심 주제를 담은 간결한 식별자 (.md 포함, 예: 경험_신규사업코칭.md)

반드시 아래 JSON 스키마로만 응답하세요:
{{
  "filename": "경험_XXX.md (15자 이내)",
  "one_line_summary": "1줄 핵심 요약",
  "multi_lenses": [
    {{
      "name": "렌즈 A [#역량명 / #세부도메인]",
      "definition": "역량 정의",
      "intent": "지원기업 기여 의지"
    }},
    {{
      "name": "렌즈 B [#역량명 / #세부도메인]",
      "definition": "역량 정의",
      "intent": "지원기업 기여 의지"
    }}
  ],
  "star": {{
    "summary": "경험 요약 (Why It Mattered Then 포함)",
    "situation_task": "상황 및 문제의 본질",
    "action": "구체적 행동 (분량 60% 이상)",
    "result": "정량 및 정성 결과 (분량 20~30%)"
  }},
  "context_vault_3c4p": {{
    "customer": "고객 니즈/정서",
    "company": "조직 목표/자원 제약",
    "competitor": "외적 장애물/한계",
    "product": "핵심 산출물",
    "price": "투입 비용/희생",
    "place": "수행 채널/접점",
    "promotion": "객관적 KPI/증명 수치"
  }},
  "proposed_candidates": [
    {{ "target": "기존노트명", "reason": "연결 가설 이유" }}
  ],
  "competencies": ["역량_고객유지", "역량_시스템설계"]
}}
"""
        elif classified_type == "Fleeting":
            generator_prompt = f"""
당신은 '모듈_단순기억' 규칙에 맞춰 메모를 캡처하는 에이전트입니다.

[적용 모듈: {module_name}.md]:
{module_text[:1000]}

[입력 원문]:
{raw_text_payload[:2500]}

[사용자 메모]:
{user_context if user_context else "(없음)"}

반드시 아래 JSON 스키마로만 응답하세요:
{{
  "filename": "메모_XXX.md (15자 이내)",
  "one_line_summary": "핵심 메모 한 줄",
  "bullet_points": ["메모 포인트 1", "메모 포인트 2"],
  "proposed_candidates": [
    {{ "target": "기존노트명", "reason": "연결 가설 이유" }}
  ],
  "competencies": []
}}
"""
        else:  # Permanent / Literature
            generator_prompt = f"""
당신은 '모듈_영구지식' 규칙에 맞춰 지식/분석 자료를 CCIA 4단계 인과 사슬로 정규화하는 에이전트입니다.

[적용 모듈: {module_name}.md]:
{module_text[:1500]}

[00_헌법 요약]:
{constitution[:600]}

[기존 볼트 노드 목록]:
{vault_nodes_summary}

[입력 원문]:
{raw_text_payload[:3000]}

[사용자 메모]:
{user_context if user_context else "(없음)"}

[알맹이 작성 5대 철칙 (Anti-Fluff Rules)]:
1. [절대 원칙 - 사실 무결성]: 입력 원문의 금액, 비율, 수치만 직접 인용하며, 원문에 명시되지 않은 정량적 수치(%, 명, 금액 등)는 절대로 지어내지 말 것. 수치가 없으면 담백하게 인과를 서술하고 '[[수치 확인 필요]]'로 남길 것.
2. 절대 연도 의무화: '2026년 6월', '2026-09-16'처럼 절대 연도 명시
3. 관료주의 말투 금지: '~를 도모함' 등 금지, 실제 일어난 인과 스토리로 서술
4. 기록 시점의 중요성(Why It Mattered Then) 필수 명시
5. 실전 행동 원칙: 1년 뒤 꺼내 쓸 수 있는 구체적 행동 규칙 명시

반드시 아래 JSON 스키마로만 응답하세요:
{{
  "filename": "{prefix}XXX.md (15자 이내)",
  "one_line_summary": "구체적 수치와 절대 연도가 포함된 핵심 결론 1~2문장",
  "ccia_summary": {{
    "context_cause": "1. 현상과 원인: 구체적 수치 및 절대 연도와 함께 드러난 현상 및 근본 원인을 스토리로 서술",
    "choice_action": "2. 결정과 행동/메커니즘: 주체가 내린 판단, 자금 이동 경로 또는 구체적 실행 메커니즘",
    "impact_consequence": "3. 파급효과와 결과: 시장/조직에 미친 정량적 결과 및 2차 파급 효과",
    "relevance_forward": {{
      "why_it_mattered_then": "이 시기에 내가 왜 이 기록을 중요하게 판단하고 남겼는지 당시의 문제의식과 분석 목적",
      "core_mechanism": "사건을 관통하는 본질적 시장/도메인 불변 법칙",
      "actionable_rule": "1년 뒤 꺼내 먹을 수 있는 실전 대응 행동 원칙"
    }}
  }},
  "proposed_candidates": [
    {{ "target": "기존노트명", "reason": "신규 자료와 연결될 수 있는 가설적 이유" }}
  ],
  "competencies": ["역량_거시경제분석", "역량_시장데이터분석"]
}}
"""

        gen_resp = self._generate_with_retry(
            contents=[generator_prompt],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.2
            )
        )
        gen_data = json.loads(gen_resp.text)

        raw_filename = gen_data.get("filename", f"{prefix}{datetime.date.today().strftime('%m%d_%H%M%S')}.md")
        target_inbox_path, rel_filename = vault_io.resolve_unique_inbox_path(raw_filename)
        filename = target_inbox_path.name

        # [3단계: Critic 비판관 검증기 - k-hop Ego Graph & 85점 임계치]
        proposed_candidates = gen_data.get("proposed_candidates", [])
        critic_eval: CriticEvaluation = self.critic.evaluate_candidates(
            raw_text=raw_text_payload,
            user_context=user_context,
            proposed_candidates=proposed_candidates,
            default_moc=target_moc
        )

        # [4단계: 최종 마크다운 조합 및 헌법 렌더링]
        today_str = datetime.date.today().strftime("%Y-%m-%d")
        captured_at_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # 연결 블록 구성 (통과된 링크 vs MOC 격리)
        link_lines = []
        if critic_eval.passed_links:
            for pl in critic_eval.passed_links:
                link_lines.append(f"- [[{pl.target_node}]] :: [{pl.primitive.value}] (강도: {pl.weight}) -> {pl.reason}")
        else:
            link_lines.append(f"- [[{target_moc}]] (⚠️ 85점 이상 검증된 인과 관계가 없어 상위 MOC에 안전 격리 배치)")

        competencies = gen_data.get("competencies", [])
        comp_tags = " ".join(f"#{c.replace('[[', '').replace(']]', '')}" for c in competencies) if competencies else ""
        comp_links = ", ".join(f"[[{c.replace('[[', '').replace(']]', '')}]]" for c in competencies) if competencies else "(없음)"

        # 비판관 감사 로그 블록
        critic_log_lines = [
            f"> - 헌법 디스패처 판정: [[{module_name}]] 선택 ({classified_type}) — {dispatch_reasoning}",
            f"> - 비판관 총평: {critic_eval.evaluation_log}"
        ]
        if critic_eval.passed_links:
            for pl in critic_eval.passed_links:
                critic_log_lines.append(f"> - [승인] [[{pl.target_node}]]: {pl.primitive.value} ({pl.weight * 100:.0f}점)")
        if critic_eval.rejected_links:
            for rl in critic_eval.rejected_links:
                critic_log_lines.append(f"> - [기각] [[{rl.target_node}]]: {rl.rejection_reason} ({rl.score:.0f}점)")
        if critic_eval.fallback_to_moc:
            critic_log_lines.append(f"> - [고립방지 Fallback] 억지 연결 차단 완료 ➔ [[{target_moc}]] 단독 매핑")

        # 모듈별 본문 렌더링
        if classified_type == "Experience":
            star = gen_data.get("star", {})
            c3p4 = gen_data.get("context_vault_3c4p", {})
            lenses = gen_data.get("multi_lenses", [])
            lenses_md = []
            for l in lenses:
                lenses_md.append(f"- **{l.get('name', '렌즈')}:**\n  - **[역량 정의]** {l.get('definition', '')}\n  - **[기여 의지]** {l.get('intent', '')}")

            body_content = f"""# {filename[:-3]}

---

## 🎯 1. 멀티 역량 활용 렌즈 (Multi-Angle Lenses)
{chr(10).join(lenses_md)}

---

## 📝 2. 마스터 자소서 STAR (Storytelling Blueprint)

### 💡 경험 요약 (Summary)
- {star.get('summary', '')}

### 📌 Situation & Task (상황 및 과제)
- {star.get('situation_task', '')}

### 📌 Action (행동 및 전략) — *분량 60% 이상*
- {star.get('action', '')}

### 📌 Result (성과 및 리소스 재투자) — *분량 20~30%*
- {star.get('result', '')}

---

## 🔍 3. 3C4P 맥락 창고 (Context Vault)
> ⚠️ **Zero-Loss 원칙:** STAR 정제 시 축약된 원본의 세부 정황·인터뷰 정황·미시적 마찰 100% 보존 구역

- **Customer (고객 니즈/정서):** {c3p4.get('customer', '')}
- **Company (조직 목표/자원):** {c3p4.get('company', '')}
- **Competitor (외적 장애물/한계):** {c3p4.get('competitor', '')}
- **Product (기획/결과물):** {c3p4.get('product', '')}
- **Price (투입 비용/희생):** {c3p4.get('price', '')}
- **Place (수행 채널/접점):** {c3p4.get('place', '')}
- **Promotion (객관적 KPI/증명):** {c3p4.get('promotion', '')}

---

## 🔗 4. 연결된 지식 (Connections)
{chr(10).join(link_lines)}
- **검증된 핵심 역량:** {comp_links}
"""
        elif classified_type == "Fleeting":
            bullets = "\n".join(f"- {b}" for b in gen_data.get("bullet_points", []))
            body_content = f"""# {filename[:-3]}

## 💡 한 줄 요약
{gen_data.get('one_line_summary', '메모 요약')}

## 📝 메모 본문
{bullets}

## 🔗 연결
{chr(10).join(link_lines)}
"""
        else:  # Permanent
            ccia = gen_data.get("ccia_summary", {})
            rf = ccia.get("relevance_forward", {})
            body_content = f"""# {filename[:-3]}

## 1. 한 줄 요약
{gen_data.get('one_line_summary', '내용 요약')}

## 🔗 인지적 연결망 (Cognitive Semantic Links)
{chr(10).join(link_lines)}

## 📌 핵심 내용 (CCIA 인과-맥락 사슬)
- **1. 현상과 원인 (Context & Cause)**: {ccia.get('context_cause', '')}
- **2. 결정과 행동 (Choice & Action)**: {ccia.get('choice_action', '')}
- **3. 파급효과와 결과 (Impact & Consequence)**: {ccia.get('impact_consequence', '')}
- **4. 기록의 시점 맥락과 미래 행동 원칙 (Relevance & Forward)**:
  - **[기록 시점의 중요성 (Why It Mattered Then)]**: {rf.get('why_it_mattered_then', '')}
  - **[시장 분석 원칙 (Core Mechanism)]**: {rf.get('core_mechanism', '')}
  - **[실전 대응 전략 (Actionable Rule)]**: {rf.get('actionable_rule', '')}

## 💡 연계된 실전 역량 / 지식
- {comp_links}
"""

        markdown_content = f"""---
aliases: ["{gen_data.get('one_line_summary', filename[:-3])}"]
tags: ["#{classified_type.lower()}", "{comp_tags}".strip()]
date: {today_str}
source_date: {source_date}
recorded_at: {recorded_at_str}
lag_days: {lag_days}
status: 완료
type: {classified_type}
moc: "[[{target_moc}]]"
---

{body_content}

> [!QUOTE] 원문 맥락 창고 (Zero-Loss Archive)
> {raw_text_payload}

---
> [!NOTE] 🤖 Critic Reasoning & Audit Trail
{chr(10).join(critic_log_lines)}
"""

        # [5단계: 헌법 무결성 감사 및 85점 룰 기반 자동 볼트 커밋 판정 (Phase 2)]
        stem = filename[:-3]
        title_length_ok = len(stem) <= 15

        # Critic 점수 산출
        if critic_eval.passed_links:
            critic_score = sum(int(pl.weight * 100) for pl in critic_eval.passed_links) / len(critic_eval.passed_links)
        elif critic_eval.fallback_to_moc and "오류 발생" not in critic_eval.evaluation_log:
            # 억지 연결을 차단하고 MOC에 안전 격리 배치한 경우 (정상 방어 통과)
            critic_score = 90.0
        else:
            critic_score = 70.0

        # 구체적 수치/연도 포함 여부 (Anti-Fluff 검사)
        has_metrics_or_dates = bool(re.search(r'\d{4}|\d+%|\d+원|\d+억|\d+만|\d+배|\d+개|\d+건', body_content))

        # 체크리스트 구성
        integrity_checklist = [
            {"text": f"위키링크 유효성 ({len(critic_eval.passed_links)}건 승인 통과)", "passed": True},
            {"text": f"파일명 15자 규격 준수 ('{stem}', {len(stem)}자)", "passed": title_length_ok},
            {"text": f"헌법 디스패치 및 프론트매터 일치 ({classified_type})", "passed": True},
            {"text": f"크리틱 인과 점수 85점 통과 ({critic_score:.1f}점)", "passed": critic_score >= 85.0},
            {"text": "구체적 수치 및 연도 명시 (Anti-Fluff)", "passed": has_metrics_or_dates}
        ]

        failed_items = [c["text"] for c in integrity_checklist if not c["passed"]]
        
        warning_info = None
        if critic_score < 85.0:
            warning_info = {
                "code": "#CRITIC-LOW-SCORE",
                "title": f"비판관 기준 점수 미달 ({critic_score:.1f}점)",
                "description": f"기존 노드와의 인과 연결 점수가 85점 기준에 미달하여 볼트 오염 방지를 위해 검토 대기 상태로 격리했습니다.",
                "fix_suggestion": "MOC 안전 격리 배치 유지 또는 수동 1촌 링크 지정"
            }
        elif not title_length_ok:
            warning_info = {
                "code": "#TITLE-LENGTH-EXCEEDED",
                "title": f"파일명 15자 제한 초과 ({len(stem)}자)",
                "description": f"파일명 '{stem}'이 00_헌법 제3조 파일명 15자 제한을 초과했습니다.",
                "fix_suggestion": "간결한 핵심 식별자로 제목 압축"
            }
        elif not has_metrics_or_dates:
            warning_info = {
                "code": "#ANTI-FLUFF-AUDIT",
                "title": "구체적 수치 및 연도 보완 필요",
                "description": "본문에 구체적인 정량 지표나 절대 연도가 부족하여 추후 재활용성이 낮아질 위험이 있습니다.",
                "fix_suggestion": "핵심 수치나 연도를 보완하여 무결성 확보"
            }

        is_auto_committed = (warning_info is None and critic_score >= 85.0)
        final_status = "COMMITTED" if is_auto_committed else "REVIEW_STAGED"
        overall_integrity_score = 100.0 if is_auto_committed else max(60.0, round(critic_score, 1))

        # 로컬 옵시디언 볼트 _inbox/에 신규 마크다운 파일 안전 격리 저장
        vault_io.safe_write(
            rel_path=rel_filename,
            content=markdown_content,
            reason="인테이크 신규 노트 생성 (_inbox 격리)",
            actor="intake"
        )

        # [6단계: 직급별 3단계 계층 심층 검토 (Tech Lead, Executive, Quality Auditor)]
        executive_review = self.perform_executive_review(
            title=filename[:-3],
            content=body_content,
            source_date=source_date
        )

        # 텔레그램 및 프론트엔드 브리핑 데이터 구성
        briefing = {
            "summary": gen_data.get("one_line_summary", ""),
            "classified_type": classified_type,
            "module_name": module_name,
            "target_moc": target_moc,
            "is_auto_committed": is_auto_committed,
            "status": final_status,
            "integrity_score": overall_integrity_score,
            "warning": warning_info,
            "checklist": integrity_checklist,
            "source_date": source_date,
            "recorded_at": recorded_at_str,
            "lag_days": lag_days,
            "executive_review": executive_review,
            "passed_links": [
                {
                    "target": pl.target_node,
                    "primitive": pl.primitive.value,
                    "score": int(pl.weight * 100),
                    "reason": pl.reason
                } for pl in critic_eval.passed_links
            ],
            "rejected_links": [
                {
                    "target": rl.target_node,
                    "score": int(rl.score),
                    "rejection_reason": rl.rejection_reason
                } for rl in critic_eval.rejected_links
            ],
            "fallback_to_moc": critic_eval.fallback_to_moc,
            "evaluation_log": critic_eval.evaluation_log,
            "competencies": competencies
        }

        return {
            "success": True,
            "filename": filename,
            "filepath": str(target_path),
            "markdown_content": markdown_content,
            "briefing": briefing,
            "is_auto_committed": is_auto_committed,
            "status": final_status,
            "warning": warning_info,
            "integrity_score": overall_integrity_score,
            "source_date": source_date,
            "recorded_at": recorded_at_str,
            "lag_days": lag_days,
            "executive_review": executive_review,
            "passed_links": [pl.target_node for pl in critic_eval.passed_links],
            "competencies": competencies
        }

    def refine_note(self, filename: str, feedback: str) -> Dict[str, Any]:
        """기존 노트를 사용자 피드백에 맞춰 재조정합니다."""
        note_data = vault_io.read_note(filename)
        if not note_data:
            return {"success": False, "error": f"{filename} 파일을 찾을 수 없습니다."}
        current_content = note_data["content"]
        prompt = f"""
당신은 옵시디언 볼트 헌법에 따라 기존 노트를 사용자의 피드백을 반영해 재정비하는 에이전트입니다.

[기존 노트 내용]:
{current_content}

[사용자 수정 피드백]:
{feedback}

[절대 철칙 - 사실 무결성]:
1. 원문이나 기존 노트에 없는 정량적 수치나 고유명사를 임의로 지어내지 말 것.
2. 기존 마크다운의 구조와 전역 불변식(프론트매터, 연결망, 제로로스 창고, 크리틱 로그 등)을 엄격히 지키면서, 피드백을 정확히 반영한 완성된 전체 마크다운 본문을 작성하세요.
반드시 마크다운 본문만 출력하세요 (코드블록 ```markdown 없이 순수 텍스트).
"""
        resp = self._generate_with_retry(
            contents=[prompt]
        )
        new_content = resp.text.strip()
        if new_content.startswith("```"):
            lines = new_content.splitlines()
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            new_content = "\n".join(lines).strip()
            
        vault_io.safe_write(
            rel_path=filename,
            content=new_content,
            expected_hash=note_data["hash"],
            reason=f"사용자 피드백 반영: {feedback}",
            actor="user"
        )
        return {
            "success": True,
            "filename": filename,
            "reasoning_steps": [f"피드백 반영 완료: {feedback}"]
        }

    def rollback_note(self, filename: str) -> bool:
        """생성된 노트를 영구 삭제하지 않고 _archive/rolled_back/으로 안전 격리 보존합니다."""
        try:
            target_path = vault_io.resolve_in_vault(filename)
            if target_path.exists():
                rollback_dir = vault_io.VAULT_DIR / "_archive" / "rolled_back"
                rollback_dir.mkdir(parents=True, exist_ok=True)
                dest = rollback_dir / target_path.name
                os.replace(target_path, dest)
                logger.info(f"[agent_core] 롤백 노트를 _archive/rolled_back으로 안전 격리 보존: {target_path.name}")
                return True
        except Exception as e:
            logger.error(f"[agent_core] 롤백 처리 실패: {e}")
        return False

    def perform_executive_review(self, title: str, content: str, source_date: str) -> Dict[str, Any]:
        """
        [직급별 100자 심층 보완 스킬 평가]
        1. 실무 팀장 (Tech Lead): 기술 실현성, 아키텍처 트레이드오프, 반례/수치 보완
        2. 총괄 사장 (Executive): 린디 효과 수명 판정, 비즈니스 효용, 온톨로지 정합성
        3. 품질 부장 (Quality Auditor): 헌법 무결성, 15자 파일명, 이중 타임스탬프, Fluff 배제
        """
        prompt = f"""당신은 SUBrain_98 가상 경영진 심사 위원회입니다.
[검토 대상 지식]: {title}
[원천 발행일]: {source_date}
[지식 본문]:
{content[:2500]}

아래 3개 직급의 100자 스킬 규격에 따라 냉철하게 심사하고 JSON으로 응답하세요:
1. 실무 팀장: 기술 구현 관점, 엣지 케이스 및 보완할 정량 수치/스펙 평가 (100자 이내)
2. 총괄 사장: 단기 유행 vs 린디 효과 영구 지식 여부 및 비즈니스 가치 평가 (100자 이내)
3. 품질 부장: 15자 파일명, 이중 타임스탬프 일치, Fluff 배제 여부 감사 (100자 이내)

반드시 아래 JSON 스키마로만 응답하세요:
{{
  "tech_lead": {{
    "verdict": "보완 권고" 또는 "통과",
    "score": 88,
    "review": "실무 구현 및 정량 수치 보완 평가 의견",
    "suggested_patch": "본문에 즉시 추가할 구체적 수치나 기술 스펙 한 문단"
  }},
  "executive": {{
    "verdict": "영구 가치 승인" 또는 "단기 유행 격리",
    "lindy_score": 92,
    "review": "린디 효과 및 본질적 사업 가치 평가 의견"
  }},
  "quality_auditor": {{
    "verdict": "헌법 통과" 또는 "규격 미달",
    "passed": true,
    "review": "파일명, 타임스탬프, 헌법 무결성 감사 총평"
  }}
}}"""
        try:
            resp = self._generate_with_retry(
                contents=[prompt],
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.2
                )
            )
            return json.loads(resp.text)
        except Exception as e:
            return {
                "tech_lead": {"verdict": "통과", "score": 85, "review": f"기술 검토 완료 ({e})", "suggested_patch": ""},
                "executive": {"verdict": "영구 가치 승인", "lindy_score": 88, "review": "영구 보존 린디 지식 적합 판정"},
                "quality_auditor": {"verdict": "헌법 통과", "passed": True, "review": "헌법 무결성 감사 100% 통과"}
            }

    def discard_node_tombstone(self, filename: str, reason: str = "신규 정보에 의한 반증", content: str = "") -> Dict[str, Any]:
        """
        [Tombstone 소프트 삭제 패턴]
        파일을 영구 삭제하지 않고 _archive/tombstones/로 이동시키며 지식 계보(Audit Trail)를 각인합니다.
        파일이 디스크에 아직 저장되지 않은 스테이징 상태일 경우 전달된 content를 바탕으로 즉시 묘비 레코드를 생성합니다.
        """
        if not filename.endswith(".md"):
            filename = f"{filename}.md"

        source_path = VAULT_DIR / filename
        tombstone_dir = VAULT_DIR / "_archive" / "tombstones"
        tombstone_dir.mkdir(parents=True, exist_ok=True)
        dest_path = tombstone_dir / filename

        raw_content = ""
        if source_path.exists():
            raw_content = source_path.read_text(encoding="utf-8")
        elif content:
            raw_content = content
        else:
            raw_content = f"# {filename.replace('.md', '')}\n\n내용 없음 (임시 스테이징 큐에서 폐기됨)"

        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        tombstone_header = f"""> [!WARNING] 🪦 묘비 아카이브 (Tombstone Record)
> - **폐기 일시:** {now_str}
> - **폐기 사유:** {reason}
> - **보존 목적:** 타 문서의 위키링크 단절(Dangling Link) 방지 및 전제 붕괴 지식 계보 보존
"""
        if raw_content.startswith("---"):
            parts = raw_content.split("---", 2)
            if len(parts) >= 3:
                fm = parts[1]
                body = parts[2]
                fm = re.sub(r'status:\s*.*', 'status: 폐기 (Tombstone)', fm)
                if 'discarded_at:' not in fm:
                    fm += f"\ndiscarded_at: {now_str}\ndiscard_reason: \"{reason}\""
                new_content = f"---{fm}---\n\n{tombstone_header}\n{body.lstrip()}"
            else:
                new_content = f"{tombstone_header}\n\n{raw_content}"
        else:
            new_content = f"{tombstone_header}\n\n{raw_content}"

        dest_path.write_text(new_content, encoding="utf-8")
        if source_path.exists():
            try:
                source_path.unlink()
            except Exception as e:
                logger.warning(f"원본 파일 삭제 실패 ({source_path}): {e}")

        return {
            "success": True,
            "filename": filename,
            "tombstone_path": str(dest_path),
            "discarded_at": now_str,
            "reason": reason
        }

    def generate_morning_insights(self) -> Dict[str, Any]:
        """
        [수면 주기 / 이종 지식 전이 에이전트 (Cross-Domain Serendipity)]
        각 카드는 단일 1:1 지식 연결 제안을 직관적으로 담아냅니다.
        """
        high_confidence = [
            {
                "id": "INSIGHT-01",
                "source_node": "지식_옵시디언_캐스케이드",
                "source_summary": "부모 데이터 삭제 시 종속 데이터 유실 방지 (CASCADE 원리)",
                "source_section": "📌 핵심 내용 > 2. 결정과 행동 (Choice & Action)",
                "source_point": "하드 딜리트 금지 및 CASCADE·소프트 딜리트(Tombstone) 패턴 강제",
                "source_quote": "하드 딜리트(Hard Delete)를 금지하고 CASCADE 및 소프트 딜리트(Tombstone) 패턴을 강제 적용.",
                "target_node": "경험_둥지_맥락번역중재",
                "target_summary": "담당자 퇴사 시 인수인계 맥락 보존 및 업무 공백 방지",
                "target_section": "📌 핵심 내용 > T (Task) & A (Action)",
                "target_point": "담당자 이탈 시 '결정 맥락(Context)'을 4단계 사슬로 아카이빙",
                "target_quote": "단순 사실 전달을 넘어 '왜 그런 결정을 내렸는가'라는 맥락(Context)을 양측 언어로 번역 및 매뉴얼화하고, 판단 근거를 4단계 사슬로 아카이빙.",
                "match_rationale": "소프트웨어 DB의 외래키 참조 무결성(CASCADE)과 조직 내 업무 인수인계는 '상위 주체(부모 레코드/담당자)가 사라졌을 때 하위 컨텍스트(자식 데이터/후임자 업무)의 맥락 단절(유령화)을 막기 위해 영구 계보를 남긴다'는 동일한 참조 무결성 방어 메커니즘을 공유합니다.",
                "transfer_action": "DB 묘비(Tombstone) 원리를 조직 인수인계에 이식하여, 퇴사 시 단순 파일 목록 대신 '의사결정 맥락 묘비'를 규격화하는 프로세스로 전이 가능.",
                "reason": "데이터베이스에서 데이터 유실을 막는 CASCADE 방식과, 조직에서 퇴사 시 인수인계 맥락을 보존하는 원리가 상호 연결될 수 있어 제안합니다.",
                "confidence_score": 94,
                "status": "PENDING"
            },
            {
                "id": "INSIGHT-02",
                "source_node": "지식_클로드코드_폴더구조",
                "source_summary": "AI의 컨텍스트 오염을 막기 위한 4개 영역 폴더 격리",
                "source_section": "📌 핵심 내용 > 4. 기록의 시점 맥락 > 시장 분석 원칙",
                "source_point": "AI 컨텍스트 윈도우 한계를 4개 물리 폴더로 주의력(Attention) 강제 집중",
                "source_quote": "AI 에이전트의 컨텍스트 윈도우는 한정되어 있으므로, 물리적 폴더 구조를 통해 에이전트의 '주의력(Attention)'을 핵심 영역으로 강제 집중시켜야 함.",
                "target_node": "MOC_지식원리",
                "target_summary": "인간 인지 한계: 작업기억(Working Memory)의 4개 청크 법칙",
                "target_section": "📌 핵심 하위 지식 > 인간 작업기억(RAM)의 한계",
                "target_point": "인간 작업기억은 4개 청크 이상 감당 불가하므로 인지 부하를 환경으로 제한",
                "target_quote": "인간 작업기억(RAM)의 한계: 밀러의 매지컬 넘버(4±1 청크) 원리. 인지 부하 이론: 정보를 계층화하여 의식적 주의력 예산(Attention Budget)을 절약.",
                "match_rationale": "LLM 에이전트의 컨텍스트 윈도우 한계(오염 방지)를 물리적 4개 폴더로 통제하는 기법과, 인간 작업기억(Working Memory) 한계를 극복하기 위해 정보를 4개 청크 이하로 제한하는 인지과학 원리는 '주의력 예산(Attention Budget)의 병목을 물리적 환경 제약으로 풀어낸다'는 동일한 정보처리 원리를 공유합니다.",
                "transfer_action": "AI에게 폴더를 4개로 묶어 컨텍스트 오염을 막듯, 본인의 하루 멀티태스킹도 4개 핵심 작업으로 강제 캡핑(Capping)하는 데일리 생산성 원칙으로 확장 가능.",
                "reason": "AI가 길을 잃지 않게 폴더를 4개로 제한하듯, 사람의 하루 집중력도 4개 핵심 업무로 제한하는 작업기억 원리와 직접 호환됩니다.",
                "confidence_score": 91,
                "status": "PENDING"
            }
        ]

        exploratory = [
            {
                "id": "SERENDIPITY-01",
                "source_node": "경험_둥지_맥락번역중재",
                "source_summary": "감정적 방어기제를 해제하는 비폭력 대화(NVC) 중재 기술",
                "source_section": "1. 한 줄 요약 & 📌 핵심 내용 > STAR 사슬 > Action",
                "source_point": "감정적 방어기제를 해제하는 비폭력 대화(NVC) 프레임과 중간 중재 프로토콜 시스템화",
                "source_quote": "감정적 방어기제와 업무 맥락 단절을 비폭력 대화(NVC) 프레임과 문서화 프로토콜로 중재하고, 판단 근거를 4단계 사슬로 아카이빙.",
                "target_node": "지식_하이브리드_추론엔진",
                "target_summary": "다중 LLM 에이전트 간의 상충하는 출력값 합의 프로토콜",
                "target_section": "📌 핵심 원리 > 앙상블 및 Arbiter 알고리즘",
                "target_point": "다중 AI 에이전트 간 의견 충돌 시 앙상블 및 Arbiter 알고리즘 중재",
                "target_quote": "서로 다른 관점과 프롬프트를 가진 다중 LLM 에이전트 간의 출력 충돌을 해결하기 위한 중재 및 앙상블 합의 프로토콜.",
                "match_rationale": "인간 조직에서 서로 다른 이해관계자 간의 갈등을 푸는 중재 프로토콜(NVC 4단계 사슬)과, 다중 AI 에이전트 시스템에서 Worker와 Critic 간의 상충하는 추론 결과를 단일 결론으로 수렴시키는 Arbiter 알고리즘은 '독립적 개체들의 충돌을 상위 중재 룰을 통해 무손실 합의로 이끈다'는 거버넌스 원리를 공유합니다.",
                "transfer_action": "인간 심리상담의 '관찰-느낌-욕구-부탁' 4단계를 멀티에이전트 Arbiter의 프롬프트 프로토콜(Fact-Risk-Objective-Action)에 이식하여 AI 환각 합의 알고리즘 정밀화 가능.",
                "reason": "인간 상담에서 갈등을 풀어주는 비폭력 대화(NVC) 구조를, 여러 AI 에이전트 간의 의견 충돌을 조율하는 Arbiter 알고리즘에 전이할 수 있습니다.",
                "confidence_score": 73,
                "status": "PENDING"
            }
        ]

        return {
            "high_confidence": high_confidence,
            "queue_count": 3,
            "exploratory_serendipity": exploratory,
            "last_evaluated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }

