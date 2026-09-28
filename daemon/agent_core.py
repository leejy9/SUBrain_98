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

class ConstitutionalAgent:
    def __init__(self):
        self.client = genai.Client(api_key=GEMINI_API_KEY)
        self.indexer = VaultIndexer()
        self.critic = CriticValidator(self.indexer)
        self.model_name = "gemini-3.5-flash"

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
1. 구체적 수치 및 사실 의무화 (Anti-Fluff)
2. 절대 연도 의무화 ('2024.10~2025.06', '2026-09-14' 등)
3. 당시 관점에서의 중요성(Why It Mattered Then)을 STAR 요약부에 필히 명시
4. 파일명은 15자 이내 간결한 식별자 (.md 포함, 예: 경험_신규사업코칭.md)

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
1. 구체적 수치 의무화: 원문의 금액, 비율, 수치 직접 인용
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
        if not raw_filename.endswith(".md"):
            raw_filename += ".md"
        stem = raw_filename[:-3]
        if len(stem) > 18:
            filename = stem[:15] + ".md"
        else:
            filename = raw_filename

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
captured_at: {captured_at_str}
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

        target_path = VAULT_DIR / filename
        target_path.write_text(markdown_content, encoding="utf-8")

        # 텔레그램 및 프론트엔드 브리핑 데이터 구성
        briefing = {
            "summary": gen_data.get("one_line_summary", ""),
            "classified_type": classified_type,
            "module_name": module_name,
            "target_moc": target_moc,
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
            "passed_links": [pl.target_node for pl in critic_eval.passed_links],
            "competencies": competencies
        }

    def refine_note(self, filename: str, feedback: str) -> Dict[str, Any]:
        """기존 노트를 사용자 피드백에 맞춰 재조정합니다."""
        target_path = VAULT_DIR / filename
        if not target_path.exists():
            return {"success": False, "error": f"{filename} 파일을 찾을 수 없습니다."}
        current_content = target_path.read_text(encoding="utf-8")
        prompt = f"""
당신은 옵시디언 볼트 헌법에 따라 기존 노트를 사용자의 피드백을 반영해 재정비하는 에이전트입니다.

[기존 노트 내용]:
{current_content}

[사용자 수정 피드백]:
{feedback}

기존 마크다운의 구조와 전역 불변식(프론트매터, 연결망, 제로로스 창고, 크리틱 로그 등)을 엄격히 지키면서, 피드백을 정확히 반영한 완성된 전체 마크다운 본문을 작성하세요.
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
        target_path.write_text(new_content, encoding="utf-8")
        return {
            "success": True,
            "filename": filename,
            "reasoning_steps": [f"피드백 반영 완료: {feedback}"]
        }

    def rollback_note(self, filename: str) -> bool:
        """생성된 노트를 삭제(원복)합니다."""
        target_path = VAULT_DIR / filename
        if target_path.exists():
            target_path.unlink()
            return True
        return False
