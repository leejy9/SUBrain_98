from enum import Enum
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
import datetime


class CognitivePrimitive(str, Enum):
    """지식 간의 5대 인지 원형"""
    CAUSED_BY = "CAUSED_BY"          # 인과: A의 원인이 B
    PROVES = "PROVES"                # 근거: A 주장의 실증 증거가 B
    ADAPTS_FROM = "ADAPTS_FROM"      # 차용: B의 원리를 A에 적용/응용
    CONTRASTS_WITH = "CONTRASTS_WITH"  # 대조: A와 B의 전제/결과가 충돌
    PART_OF = "PART_OF"              # 계층: A가 B 체계의 하위 구성요소


class SemanticLink(BaseModel):
    """인지적 의미가 부여된 지식 간 연결"""
    target_node: str = Field(description="연결 대상 기존 노트명")
    primitive: CognitivePrimitive = Field(description="5대 인지 원형 중 하나")
    weight: float = Field(default=0.85, ge=0.0, le=1.0, description="연결 강도 (0.0 ~ 1.0)")
    reason: str = Field(description="연결된 구체적 인과 및 논리적 맥락")


class RejectedLink(BaseModel):
    """비판관에 의해 탈락된 억지 연결"""
    target_node: str
    score: float
    rejection_reason: str


class CriticEvaluation(BaseModel):
    """Critic 비판관 검증 결과"""
    passed_links: List[SemanticLink] = Field(default_factory=list, description="85점 이상 통과된 검증 링크")
    rejected_links: List[RejectedLink] = Field(default_factory=list, description="85점 미만으로 기각된 억지 링크")
    fallback_to_moc: bool = Field(default=False, description="통과 링크가 없어 상위 MOC에 격리할지 여부")
    evaluation_log: str = Field(default="", description="비판관의 전체 평가 소견")


class PerspectiveStack(BaseModel):
    """시간적 관점 적층 메타데이터"""
    is_stacked: bool = False
    parent_past_note: Optional[str] = None
    time_horizon_years: Optional[float] = None
    reinterpretation: Optional[str] = None


class BlackboardState(BaseModel):
    """모든 모듈이 공유하는 불변 원문 및 상태 객체 (Blackboard Pattern)"""
    # 원시 입력 (불변 보존)
    raw_text: str = Field(description="사용자가 보낸 원문 전체 (절대 요약/삭제 금지)")
    source_url: Optional[str] = None
    user_context: str = Field(default="", description="사용자가 덧붙인 1줄 착상/메모")
    category_intent: str = Field(default="Experience", description="Experience | Knowledge | Company | Thought")
    timestamp: str = Field(default_factory=lambda: datetime.datetime.now().isoformat())

    # 1단계: 헌법 분류 및 파일명
    filename: Optional[str] = None
    target_moc: Optional[str] = None

    # 2단계: 후보 인출
    candidate_node_names: List[str] = Field(default_factory=list)

    # 3단계: Critic 검증 결과
    critic_result: Optional[CriticEvaluation] = None

    # 4단계: 관점 적층
    perspective: Optional[PerspectiveStack] = None

    # 5단계: 최종 출력
    markdown_content: Optional[str] = None
    briefing_summary: Optional[str] = None
    competencies: List[str] = Field(default_factory=list)
