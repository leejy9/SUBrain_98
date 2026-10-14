# 11_UNIVERSAL_INGEST_EXTRACTOR_SPEC.md
## Subrain_98 만능 인테이크 추출기 및 무결성 파이프라인 개발 계획

> **문서 상태**: 설계 완료 (Plan Mode 확정)  
> **관련 문서**: [10_PIPELINE_INTEGRITY_FIX_SPEC.md](file:///Users/grasshop/Desktop/Antigravity/Subrain_98/10_PIPELINE_INTEGRITY_FIX_SPEC.md), [00_PROJECT_LOG.md](file:///Users/grasshop/Desktop/Antigravity/Subrain_98/00_PROJECT_LOG.md)

---

### 1. 배경 및 사용자 문제의식

1. **인테이크 대상의 다변화**:
   - 사용자는 유튜브 영상, 유튜브 커뮤니티 글, 일반 웹 링크, 뉴스 기사, PDF/텍스트 파일, 단순 메모 등 다양한 형태의 입력을 텔레그램 모바일 또는 대시보드에 주입함.
2. **현행 파이프라인의 취약점**:
   - 유튜브 링크 입력 시 단순 HTML 껍데기만 긁어와 자막 본문이 0자로 유실됨.
   - 차단 방화벽(403)이나 자바스크립트 렌더링 사이트(Notion, 뉴스) 인입 시 본문 스크랩 실패.
   - 중간 알림("처리 중입니다", "카테고리 선택") 등 불필요한 채팅 노이즈가 과다함.
3. **사용자 핵심 요구사항**:
   - **군더더기 없는 단일 회신 UX**: 중간 알림 일체 없이, 분석 완료 시 **딱 1개의 정갈한 핵심 요약 및 인과 매핑 카드**만 회신할 것.
   - **무결점 텍스트 추출**: 어떤 재료가 들어와도 죽지 않고 `[원문 추출 ➔ 파편화/요약 ➔ 기존 지식 매핑]` 파이프라인이 100% 견고하게 작동할 것.

---

### 2. 4대 엔지니어링 불변식 (Extractor Invariants)

- **INV-E1 (Zero-Chatter 단일 회신 불변식)**:
  - 텔레그램 인입 시 "처리 중이에요", "이거 분석 중" 등 중간 상태 메시지 전송을 전면 배제한다.
  - 파이프라인 완료 즉시 `[핵심 요약 + 85점 인과 연결 + 역량 태그]`로 구성된 **단 1개의 최종 카드**만 전송한다.
- **INV-E2 (3중 웹 추출 그물망 불변식 - Web Cascade)**:
  - 웹 링크 인입 시 반드시 3단계 계단식 폴백을 거친다:
    - 1차: 실 브라우저 헤더 기반 `trafilatura` 정적 추출 (0.2초 초고속)
    - 2차: 1차 실패/100자 이하 시 `Jina Reader (r.jina.ai)` 자바스크립트 실행 렌더링 프록시 추출 (차단 우회)
    - 3차: 최후 방어선으로 `Gemini Search Grounding` 구글 검색 색인 캐시 회수.
- **INV-E3 (유튜브 자막 직통 추출 불변식 - Sub-Second Transcript)**:
  - 유튜브 비디오 URL 인입 시 동영상 다운로드 없이 `youtube-transcript-api`를 통해 한국어(우선) 및 자동 생성 자막 텍스트를 0.3초 만에 직접 추출한다.
  - 커뮤니티 글 및 쇼츠 특수 링크는 DOM 메타 파서로 자동 전환한다.
- **INV-E4 (원자적 조립 커밋 불변식 - Safe Assembly)**:
  - 파이프라인의 모든 데이터(요약문, 인과 연결, 역량, 브리핑 딕셔너리)가 정상 조립된 최종 순간에만 볼트 I/O를 확정하여 불완전한 고립 파일 생성을 원천 방지한다.

---

### 3. 컴포넌트 아키텍처

```
[입력: 유튜브 / 웹사이트 / 문서 파일 / 텍스트]
                       │
                       ▼
    ┌──────────────────────────────────────┐
    │  daemon/universal_extractor.py       │  <-- 신규 독립 모듈 (200줄 이내)
    │  ├─ YouTube: youtube-transcript-api   │
    │  ├─ Web: 3-Tier Cascade (Trafilatura │
    │  │       ➔ Jina Reader ➔ Grounding)  │
    │  └─ File: UTF-8 / Text Decoders      │
    └──────────────────────────────────────┘
                       │ (정제된 원문 텍스트)
                       ▼
    ┌──────────────────────────────────────┐
    │  daemon/agent_core.py                │
    │  ├─ 헌법 자동 디스패치                │
    │  ├─ CCIA / STAR 파편화 요약          │
    │  ├─ Critic 85점 인과 그래프 매핑      │
    │  └─ vault_io.safe_write 원자적 저장   │
    └──────────────────────────────────────┘
                       │ (단 1회의 완료 브로드캐스트)
                       ▼
    ┌──────────────────────────────────────┐
    │  daemon/telegram_bot.py              │
    │  └─ 정갈한 1장 요약 카드 회신        │
    └──────────────────────────────────────┘
```

---

### 4. 단계별 구현 작업 분할 (PIV Tasks)

#### Task 1: 만능 텍스트 추출기 전용 모듈 신설 (`daemon/universal_extractor.py`)
- **목표**: 200줄 이내 단일 책임 원칙 준수 모듈.
- **주요 함수**:
  - `extract_youtube(url: str) -> Optional[ExtractedContent]`
  - `extract_web_cascade(url: str) -> ExtractedContent`
  - `extract_file(path_or_bytes, filename) -> ExtractedContent`
  - `extract_universal(raw_input: str) -> ExtractedContent`

#### Task 2: 코어 에이전트 인테이크 파이프라인 연동 (`daemon/agent_core.py`)
- **수정**: 기존의 원시 `_extract_url_content`를 제거하고 `universal_extractor.extract_universal`로 교체.
- **보장**: 추출된 본문 길이 및 출처 메타데이터가 `Zero-Loss Archive` 블록에 왜곡 없이 보존됨.

#### Task 3: 텔레그램 인테이크 UX 간소화 (`daemon/telegram_bot.py`)
- **수정**:
  - 중간 안내 메시지 및 불필요한 카테고리 핑퐁 버튼을 기본 자동 분류(헌법 자동 디스패치)로 직행.
  - 완료 시 단 1장의 정갈한 결과 보고서만 전송.
  - 수정이 필요할 때만 답장(Reply)으로 즉시 티키타카 수정 가능하도록 안내.

#### Task 4: 종단간 통합 검증 스위트 (`scripts/test_extractor_e2e.py`)
- **검증 시나리오 4종**:
  1. 실제 유튜브 비디오 자막 추출 정상 동작 확인
  2. 봇 차단 언론사/포털(네이버 뉴스) 3중 그물망 추출 통과 확인
  3. 일반 블로그 웹페이지 본문 추출 확인
  4. 순수 텍스트 및 일반 메모 인입 확인

---

### 5. 수용 기준 (Acceptance Criteria)
1. 유튜브 링크를 넣었을 때 자막 텍스트가 1초 이내에 추출되어 요약에 반영된다.
2. 일반 크롤러를 차단하는 웹 링크를 넣어도 본문이 0바이트로 실패하지 않고 마크다운으로 추출된다.
3. 텔레그램에 링크를 전송했을 때 중간 노이즈 메시지 없이, 1개의 완결된 결과 카드만 도착한다.
4. 모든 검증 테스트(`scripts/test_extractor_e2e.py`)가 100% Green Pass를 달성한다.
