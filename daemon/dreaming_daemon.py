import json
import logging
from typing import Dict, List, Optional
from google import genai
from google.genai import types

try:
    from config import GEMINI_API_KEY
    from moc_service import MOCService, CONSTITUTIONAL_MOCS
    from vault_indexer import VaultIndexer
except ImportError:
    from daemon.config import GEMINI_API_KEY
    from daemon.moc_service import MOCService, CONSTITUTIONAL_MOCS
    from daemon.vault_indexer import VaultIndexer

logger = logging.getLogger("DreamingDaemon")

class DreamingDaemon:
    """
    Subrain_98 The Dreaming Daemon (수면 기억 공고화 & 아침 지식 인사이트 엔진).
    핵심 기능:
    1. MOC 소속 적합성 감사 (Semantic Drift Audit): LLM이 소속 노드들의 맥락을 읽고 엉뚱한 노드 탐지 및 이사 권고.
    2. MOC 이질성 분할 진단 (Heterogeneity Split Diagnosis): 정보의 다양성이 임계치를 넘었을 때 하위 MOC 신설 제안.
    3. 전 과정 자연어 풀이 브리핑 (사용자가 이해하기 쉬운 스토리텔링 진단).
    """

    def __init__(self, moc_service: Optional[MOCService] = None, indexer: Optional[VaultIndexer] = None):
        self.moc_service = moc_service or MOCService()
        self.indexer = indexer or VaultIndexer()
        self.client = genai.Client(api_key=GEMINI_API_KEY)
        self.model_name = "gemini-3.1-flash-lite"

    def get_node_snippet(self, node_name: str) -> str:
        """노드의 본문에서 Frontmatter를 제외한 실제 핵심 텍스트 스니펫 추출"""
        import re
        stem = node_name.replace(".md", "").strip()
        path = self.moc_service.vault_dir / f"{stem}.md"
        if path.exists():
            try:
                content = path.read_text(encoding="utf-8")
                clean = re.sub(r"^---\s*[\s\S]*?---\s*", "", content).strip()
                # H1 및 첫 1~2문단 추출
                return clean[:400].replace("\n", " ")
            except Exception:
                return ""
        return ""

    def audit_moc_relevance(self, moc_name: str) -> Dict:
        """
        특정 MOC 산하 노드들이 해당 MOC의 본질적 주제와 부합하는지 LLM이 심층 감사.
        기계적 벡터 거리가 아닌 자연어 풀이식 이사 권고 생성.
        """
        children = self.moc_service.get_moc_children(moc_name)
        if not children:
            return {
                "moc_name": moc_name,
                "total_nodes": 0,
                "drift_detected": False,
                "recommendations": [],
                "natural_briefing": f"'{moc_name}' 산하에 소속된 노드가 없어 감사를 건너뜁니다."
            }

        # 자식 노드들의 요약 정보 수집
        node_summaries = []
        for c in children[:30]:  # 컨텍스트 예산 통제
            snippet = self.get_node_snippet(c)
            node_summaries.append(f"- [[{c}]]: {snippet if snippet else '(요약 없음)'}")

        prompt = f"""
당신은 개인 지식 온톨로지를 관리하는 수석 지식 사서(Knowledge Architect)입니다.
현재 '{moc_name}' MOC(Map of Content) 산하에 다음 {len(node_summaries)}개의 노드들이 소속되어 있습니다.

[4대 최상위 MOC 기준]:
- MOC_커리어: 개인의 실무 경험, 커리어 이력, 역량 발휘 사례, 프로젝트 수행
- MOC_지식원리: 거시경제, 인공지능 이론, 분산 아키텍처 등 영구 불변의 도메인 원리/지식
- MOC_지원전략_합격패턴: 채용 공고 분석, 기업 분석, 자소서 전략, 면접 기출 패턴
- MOC_아이디어: 미정제 착상, 번뜩이는 영감, 메모

[소속 노드 목록]:
{chr(10).join(node_summaries)}

[감사 미션]:
1. 위 노드들 중 '{moc_name}'의 본래 성격에 맞지 않고 다른 MOC로 이사하는 것이 훨씬 자연스러운 노드가 있는지 점검하십시오.
2. 기계적인 규칙 나열이 아니라, 사람이 읽었을 때 "아 그렇구나" 하고 바로 납득할 수 있도록 자연스러운 줄거리로 설명하십시오.

반드시 아래 JSON 스키마로만 응답하십시오:
{{
  "drift_detected": true 또는 false,
  "recommendations": [
    {{
      "node": "노트파일명",
      "suggested_moc": "MOC_추천이름",
      "reasoning": "왜 이 노드가 현재 MOC보다 추천 MOC에 더 잘 어울리는지 친절하고 명확한 줄거리 풀이"
    }}
  ],
  "natural_briefing": "전체 감사를 총평하는 2~3줄의 다정한 자연어 브리핑"
}}
"""
        try:
            resp = self.client.models.generate_content(
                model=self.model_name,
                contents=[prompt],
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.2
                )
            )
            result = json.loads(resp.text)
            result["moc_name"] = moc_name
            result["total_nodes"] = len(children)
            return result
        except Exception as e:
            logger.error(f"[DreamingDaemon] audit_moc_relevance 오류: {e}")
            return {
                "moc_name": moc_name,
                "total_nodes": len(children),
                "drift_detected": False,
                "recommendations": [],
                "natural_briefing": f"감사 중 일시적 오류가 발생했습니다: {str(e)}"
            }

    def diagnose_moc_heterogeneity(self, moc_name: str) -> Dict:
        """
        MOC 산하에 정보가 지나치게 다양하게 쌓여 이질성(Heterogeneity)이 발생했는지 진단.
        단순 개수가 아니라 '정보의 결이 분화되었는지'를 LLM이 판단하여 하위 MOC 신설을 제안.
        """
        children = self.moc_service.get_moc_children(moc_name)
        if len(children) < 5:
            return {
                "moc_name": moc_name,
                "total_nodes": len(children),
                "split_recommended": False,
                "heterogeneity_level": "낮음",
                "suggested_sub_mocs": [],
                "natural_briefing": f"'{moc_name}' 산하 노드가 {len(children)}개로 아직 분할이 필요하지 않은 건강한 상태입니다."
            }

        node_summaries = []
        for c in children[:40]:
            snippet = self.get_node_snippet(c)
            node_summaries.append(f"- [[{c}]]: {snippet if snippet else '(요약 없음)'}")

        prompt = f"""
당신은 지식 성단을 설계하는 우주 지식 항해사입니다.
현재 '{moc_name}' 산하에 {len(children)}개의 노드가 모여 있습니다.

[소속 노드 목록]:
{chr(10).join(node_summaries)}

[진단 미션]:
1. 이 MOC 안에 서로 다른 뚜렷한 세부 주제/프로젝트 군집(Cluster)이 2~3개 이상 감지되는지 분석하십시오.
2. 만약 특정 주제로 3개 이상의 노드가 뚜렷하게 묶인다면, 하위 MOC(2계층 성단, 예: MOC_{moc_name.replace('MOC_', '')}_핀테크 등)로 분할을 추천하십시오.
3. 사용자가 한눈에 이해할 수 있도록 쉬운 말로 분할 이유를 풀어서 설명하십시오.

반드시 아래 JSON 스키마로만 응답하십시오:
{{
  "split_recommended": true 또는 false,
  "heterogeneity_level": "높음" 또는 "보통" 또는 "낮음",
  "suggested_sub_mocs": [
    {{
      "name": "MOC_상위약칭_하위주제",
      "rationale": "이 하위 MOC로 묶어야 하는 이유 (쉬운 자연어 풀이)",
      "candidate_nodes": ["노트1", "노트2", "노트3"]
    }}
  ],
  "natural_briefing": "전체 이질성 진단 결과를 풀어쓴 2~3줄의 다정한 자연어 브리핑"
}}
"""
        try:
            resp = self.client.models.generate_content(
                model=self.model_name,
                contents=[prompt],
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.2
                )
            )
            result = json.loads(resp.text)
            result["moc_name"] = moc_name
            result["total_nodes"] = len(children)
            return result
        except Exception as e:
            logger.error(f"[DreamingDaemon] diagnose_moc_heterogeneity 오류: {e}")
            return {
                "moc_name": moc_name,
                "total_nodes": len(children),
                "split_recommended": False,
                "heterogeneity_level": "오류",
                "suggested_sub_mocs": [],
                "natural_briefing": f"진단 중 일시적 오류가 발생했습니다: {str(e)}"
            }

    def run_morning_dreaming(self) -> Dict:
        """4대 헌법 MOC 전체를 아침 순회하여 종합 리포트 발행"""
        audit_results = {}
        split_results = {}

        for moc in sorted(list(CONSTITUTIONAL_MOCS)):
            audit_results[moc] = self.audit_moc_relevance(moc)
            split_results[moc] = self.diagnose_moc_heterogeneity(moc)

        return {
            "type": "morning_dreaming_report",
            "audits": audit_results,
            "splits": split_results
        }
