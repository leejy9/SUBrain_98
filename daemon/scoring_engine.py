import re
from typing import List, Dict, Any, Optional
from models import IngestScoreMetadata, TriageRecommendation

# 기술/비즈니스/아키텍처 전문 키워드 패턴 (정보 밀도 산출용)
TECH_TERMS = {
    "redis", "kafka", "postgresql", "mysql", "architecture", "latency", "throughput",
    "cache", "distributed", "scalability", "pipeline", "llm", "agent", "microservice",
    "token", "cost", "invariant", "schema", "api", "rest", "grpc", "ci/cd", "docker",
    "kubernetes", "k8s", "concurrency", "async", "event", "mq", "oauth", "auth",
    "트래픽", "지연시간", "처리량", "캐시", "분산", "확장성", "파이프라인", "마이크로서비스",
    "토큰", "비용", "불변식", "스키마", "동시성", "비동기", "이벤트", "인덱싱", "정규화"
}


class ScoringEngine:
    """Two-Speed Triage를 위한 3대 보조 스코어링 엔진

    1. information_density (0~100): 수치(%, 원, $, 연도 등) 및 전문 어휘 밀도
    2. vault_proximity (0~100): 기존 옵시디언 영구 노드(82개) 및 MOC 키워드와의 유사도
    3. human_intent_boost (0 or 20): 캡처 당시 사용자의 날것 메모 동봉 여부 (+20점)
    """

    @classmethod
    def calculate_information_density(cls, text: str) -> float:
        """원문 내 수치, 통계, 전문어 비율을 측정하여 정보 밀도(0~100) 산출"""
        if not text:
            return 0.0

        # 1. 정량적 수치 패턴 탐색
        numeric_patterns = [
            r'\d+(\.\d+)?%',                                   # 백분율: 15%, 3.5%
            r'\d+(,\d+)*\s*(원|만원|억원|조원|\$|USD|달러|KRW)',  # 금액
            r'\d{4}년',                                         # 연도: 2026년
            r'\d+(\.\d+)?\s*(배|건|명|회|개|TPS|QPS|ms|MB|GB|TB)', # 단위/지표
            r'\d+분기|\d+개월|\d+주'                             # 기간
        ]
        numeric_matches = 0
        for pattern in numeric_patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            numeric_matches += len(matches)

        # 2. 전문 도메인 어휘 탐색
        tokens = re.findall(r'[a-zA-Z가-힣_]+', text.lower())
        tech_matches = sum(1 for t in tokens if t in TECH_TERMS)

        total_words = max(1, len(tokens))

        # 단어 100개당 수치/전문어 비율 기준 (가중치: 수치 12점, 전문어 6점)
        raw_density = (numeric_matches * 12.0 + tech_matches * 6.0) / (total_words / 40.0)
        return float(min(100.0, max(0.0, round(raw_density, 1))))

    @classmethod
    def calculate_vault_proximity(cls, text: str, vault_notes: Optional[List[Dict[str, Any]]] = None) -> float:
        """기존 옵시디언 볼트 내 82개 영구 노드 및 MOC와의 키워드 근접도(0~100) 산출"""
        if not text or not vault_notes:
            return 30.0  # 볼트 노드가 없거나 텍스트가 없으면 중간 기본값

        text_lower = text.lower()
        text_no_space = re.sub(r'\s+', '', text_lower)

        matched_notes = 0
        total_overlap_score = 0.0

        for note in vault_notes:
            note_name = note.get("name", "").lower()
            note_h1 = note.get("h1", "").lower()

            clean_name = re.sub(r'^(경험|지식|역량|프로젝트|성과|MOC)_', '', note_name, flags=re.IGNORECASE)
            sub_keywords = [k for k in re.split(r'[_ -]', clean_name) if len(k) >= 2]
            h1_tokens = [k for k in re.split(r'[_ -]', note_h1) if len(k) >= 2]
            all_tokens = set(sub_keywords + h1_tokens)

            score_for_this_note = 0.0
            for kw in all_tokens:
                if kw in text_lower or kw in text_no_space:
                    score_for_this_note += 1.0

            if score_for_this_note > 0:
                matched_notes += 1
                total_overlap_score += min(3.0, score_for_this_note)

        # 근접도 정규화: 매칭된 노드가 2개 이상이면 50점 이상 부여
        ratio = matched_notes / max(1, min(len(vault_notes), 5))
        proximity = min(100.0, (ratio * 60.0) + (total_overlap_score * 10.0))
        return float(min(100.0, max(10.0, round(proximity, 1))))

    @classmethod
    def calculate_intent_boost(cls, user_context: Optional[str]) -> float:
        """인테이크 당시 사용자가 1자 이상의 착상/메모를 동봉했으면 +20점 부스트"""
        if user_context and len(user_context.strip()) >= 2:
            return 20.0
        return 0.0

    @classmethod
    def compute_score(
        cls,
        text: str,
        user_context: str = "",
        vault_notes: Optional[List[Dict[str, Any]]] = None
    ) -> IngestScoreMetadata:
        """3대 지표 종합 점수 및 Two-Speed Triage 추천 상태 판정

        - total_score >= 75.0: DEEP_TUNE_RECOMMENDED (🧠 딥 튜닝 권장)
        - total_score < 75.0: FAST_TRACK_ELIGIBLE (⚡ 즉시 승인 가능)
        """
        density = cls.calculate_information_density(text)
        proximity = cls.calculate_vault_proximity(text, vault_notes)
        boost = cls.calculate_intent_boost(user_context)

        # 가중합: 정보 밀도 40% + 볼트 근접도 40% + 인간 개입 부스트 20점
        total = round((density * 0.4) + (proximity * 0.4) + boost, 1)
        total = min(100.0, max(0.0, total))

        if total >= 75.0:
            rec = TriageRecommendation.DEEP_TUNE_RECOMMENDED
        else:
            rec = TriageRecommendation.FAST_TRACK_ELIGIBLE

        return IngestScoreMetadata(
            information_density=density,
            vault_proximity=proximity,
            human_intent_boost=boost,
            total_score=total,
            triage_recommendation=rec
        )
