import json
import re
from typing import List, Dict, Any, Optional
from google import genai
from google.genai import types

import logging
from config import GEMINI_API_KEY
from models import CognitivePrimitive, SemanticLink, RejectedLink, CriticEvaluation
from vault_indexer import VaultIndexer

logger = logging.getLogger(__name__)

class CriticValidator:
    """k-hop Ego Subgraph 맥락을 기반으로 5대 인지 원형 적합성 및 85점 임계치를 검증하는 비판관"""

    def __init__(self, indexer: VaultIndexer):
        self.client = genai.Client(api_key=GEMINI_API_KEY)
        self.indexer = indexer
        self.model_name = "gemini-3.1-flash-lite"
        self.enabled = True

    def evaluate_candidates(
        self,
        raw_text: str,
        user_context: str,
        proposed_candidates: List[Dict[str, str]],
        default_moc: str = "MOC_커리어"
    ) -> CriticEvaluation:
        """
        제안된 후보 노드들에 대해 상세 본문 및 1-hop 이웃 노드 맥락을 조회하여 비판적 검증을 수행합니다.
        """
        if not self.enabled:
            logger.info("[CriticValidator] 비판관 검증 비활성화 (무료 쿼터 절약 모드). 상위 MOC 격리 매핑으로 즉각 반환합니다.")
            return CriticEvaluation(
                passed_links=[],
                rejected_links=[],
                fallback_to_moc=True,
                evaluation_log="비판관 검증 비활성화 모드 (Gemini Quota Saver ON) - 상위 MOC 안전 매핑"
            )

        if not proposed_candidates:
            return CriticEvaluation(
                passed_links=[],
                rejected_links=[],
                fallback_to_moc=True,
                evaluation_log="제안된 후보 노드가 없어 상위 MOC로 격리합니다."
            )

        # 각 후보 노드의 본문 및 1-hop 이웃 정보 추출
        candidates_context = []
        for cand in proposed_candidates[:4]:
            target_name = cand.get("target", "")
            reason = cand.get("reason", "")
            detail = self.indexer.get_note_detail(target_name)
            
            if detail:
                outgoing = ", ".join(f"[[{link}]]" for link in detail.get("outgoing_links", [])[:5])
                snippet = detail["content"][:600].replace("\n", " ")
                candidates_context.append(
                    f"### 후보 노드: [[{detail['name']}]]\n"
                    f"- 1차 제안 가설: {reason}\n"
                    f"- 노드 본문 요약: {snippet}\n"
                    f"- 1-hop 이웃 노드들: {outgoing if outgoing else '없음'}\n"
                )
            else:
                candidates_context.append(f"### 후보 노드: [[{target_name}]] (본문 인출 실패, 신규 노드로 추정)")

        system_instruction = """
당신은 지식 그래프의 오염과 억지 연결(Hallucinated Linking)을 원천 차단하는 엄격한 비판적 검증관(The Critic)입니다.
신규 입력 자료와 후보 노드를 대조하여, 두 지식이 실제로 연결될 만한 가치가 있는지 0~100점으로 채점하고 5대 인지 원형을 판별하세요.

[5대 인지 원형 (Cognitive Primitives)]:
1. CAUSED_BY : 인과 관계 (새 자료의 원인이 기존 노드이거나 그 반대)
2. PROVES : 실증 근거 (기존 노드의 주장을 새 자료의 수치/사례가 증명)
3. ADAPTS_FROM : 차용 및 응용 (기존 노드의 원리를 새 자료의 도메인에 적용)
4. CONTRASTS_WITH : 반론 및 대조 (기존 노드의 결론과 새 자료의 사실이 충돌)
5. PART_OF : 구성 및 계층 (새 자료가 기존 노드 시스템의 하위 구성요소)

[엄격한 채점 규칙]:
- 단순 어휘 겹침(예: 같은 '시장', '투자', '관리' 단어 사용)은 40점 이하로 즉시 기각.
- 도메인이 완전히 다르고 인과적 연관성이 없는 경우(예: 외인 주식 매도 ↔ 반려식물)는 20점 이하 기각.
- **85점 이상만 승인**: 두 지식 간에 명확한 인과율, 논리적 증거, 실증적 메커니즘이 합치할 때만 85점 이상 부여.
- 85점 이상인 후보가 하나도 없으면 억지 링크를 맺지 말고 과감히 탈락시키세요.
"""

        user_prompt = f"""
[신규 입력 자료 원문]:
{raw_text[:2000]}

[사용자 1줄 맥락]:
{user_context if user_context else "(없음)"}

[검증 대상 후보 노드 및 이웃 맥락]:
{"".join(candidates_context)}

반드시 아래 JSON 스키마로만 응답하세요:
{{
  "evaluations": [
    {{
      "target_node": "후보노트명",
      "score": 88.5,
      "primitive": "CAUSED_BY",
      "passed": true,
      "reason": "신규 기사의 환율 급등과 외인 매도 메커니즘이 기존 노드의 거시경제 분석과 인과적으로 직접 맞물림",
      "rejection_reason": ""
    }},
    {{
      "target_node": "억지후보노트명",
      "score": 35.0,
      "primitive": "PART_OF",
      "passed": false,
      "reason": "",
      "rejection_reason": "단순히 시장이라는 단어만 겹칠 뿐, 반려식물 트렌드와 거시경제 외인 매도는 아무런 인과/실증 관계가 없음"
    }}
  ],
  "overall_critique": "전체적인 연결 정합성 평가 요약"
}}
"""

        try:
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=[user_prompt],
                config=types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    temperature=0.1,
                    response_mime_type="application/json"
                )
            )
            data = json.loads(response.text)
        except Exception as e:
            # LLM 에러 발생 시 안전하게 MOC 격리 Fallback
            return CriticEvaluation(
                passed_links=[],
                rejected_links=[],
                fallback_to_moc=True,
                evaluation_log=f"Critic LLM 검증 중 오류 발생: {e}"
            )

        passed = []
        rejected = []

        for item in data.get("evaluations", []):
            score = float(item.get("score", 0.0))
            target = item.get("target_node", "").replace("[[", "").replace("]]", "")
            primitive_str = item.get("primitive", "PART_OF")
            
            # Enum 매핑
            try:
                primitive = CognitivePrimitive(primitive_str)
            except ValueError:
                primitive = CognitivePrimitive.PART_OF

            if score >= 85.0:
                passed.append(SemanticLink(
                    target_node=target,
                    primitive=primitive,
                    weight=round(score / 100.0, 2),
                    reason=item.get("reason", "검증관 승인 링크")
                ))
            else:
                rejected.append(RejectedLink(
                    target_node=target,
                    score=score,
                    rejection_reason=item.get("rejection_reason", f"기준 점수(85점) 미달: {score}점")
                ))

        fallback = (len(passed) == 0)

        return CriticEvaluation(
            passed_links=passed,
            rejected_links=rejected,
            fallback_to_moc=fallback,
            evaluation_log=data.get("overall_critique", "")
        )
