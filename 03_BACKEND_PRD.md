# Subrain_98 백엔드 엔진 PRD (Product Requirements Document)

> **문서 버전**: v1.0 (Backend Core Specification)  
> **작성일**: 2026-09-18  
> **상태**: 기획 및 설계 완료 (Ready for Implementation)  
> **기준 규칙**: `prd-planner` 스킬 준수, `critical_partnership` 맹점 분석 반영

---

## 1. 문제 정의 및 배경 (Problem Statement & Context)

### 1.1 해결하려는 본질적 문제
* **수집 마찰(Friction)**: 모바일에서 캡처한 지식이 정리되지 않은 채 폴더 속에 방치되는 '디지털 무덤' 현상.
* **억지 연결(Hallucinated Linking)**: 키워드 유사도에 의존한 무조건적 링크 형성으로 지식 그래프가 오염되는 현상(예: 외인 주식 매도 ↔ 반려식물).
* **정체된 시점(Static Context)**: 과거의 미숙한 기록과 현재의 성숙한 인사이트가 충돌할 때 발생하는 시차 왜곡.
* **무의식적 조합의 부재**: 인간의 뇌는 수면 중 서로 다른 기억을 결합하여 창의적 도약을 만들어내지만, 일반 노트 앱은 사용자가 직접 검색하지 않으면 영원히 잠들어 있음.

### 1.2 비목표 (Non-Goals)
* 본 PRD에서는 복잡한 웹 프론트엔드 UI(Next.js 화면, 3D Canvas 렌더링)는 범위에서 제외하며, **오직 데이터 파이프라인, 에이전트 추론 엔진, 로컬 볼트 I/O, 야간 데몬**의 백엔드 무결성에만 집중한다.

---

## 2. 핵심 아키텍처 및 데이터 흐름: 공유 상태(Blackboard) 패턴

에이전트 간 '전화 말잇기 게임'으로 인한 맥락 소실(Context Dilution)을 원천 차단하기 위해, 모든 백엔드 모듈은 불변의 **공유 상태 객체(Blackboard State)**를 전달받아 자기 영역의 메타데이터만 덧붙인다.

```
[Ingestion Payload] 
       │
       ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Shared Blackboard State                      │
│ - raw_text: string (절대 변경/요약 금지, 100% 원문 보존)         │
│ - source_meta: { url, author, timestamp, platform }             │
│ - classification: { type, target_moc, filename }                │
│ - candidate_retrievals: [ { note_title, ego_subgraph, sim } ]   │
│ - critic_evaluation: { passed_links, rejected_links, reasoning } │
│ - perspective_layer: { is_stacked, parent_note, reinterpretation}│
└─────────────────────────────────────────────────────────────────┘
       │
       ▼
[Final Markdown Assembler & Vault Committer]
```

---

## 3. 기능 요구사항 명세 (Functional Requirements - FR)

### FR-1. 수집 및 인테이크 게이트웨이 (Ingestion Gateway) [P0]
* **기능**:
  - 모바일(Telegram Webhook/Poller 및 추후 Web Share Target API)로부터 페이로드 수신.
  - URL 전달 시 Zero-Loss Scraper가 작동하여 본문 텍스트 추출.
  - 음성 파일 전달 시 Whisper API를 통해 텍스트 자동 전사.
* **출력**: 불변 원문(`raw_text`)이 포함된 Blackboard State 초기화.

### FR-2. 헌법 구조화 및 1차 분류기 (Constitutional Classifier) [P0]
* **기능**:
  - `00_헌법.md` 기본 원칙에 따라 글의 본질을 4대 유형(`경험`, `지식`, `기업`, `단상`) 중 하나로 분류.
  - 분류된 유형에 대응하는 기본 `[[MOC_XXX]]`를 지정.
  - 헌법 §1.2 명명 규칙에 따라 **15자 이내의 간결하고 직관적인 파일명** 생성 (예: `경험_외인매도분석`).

### FR-3. 하이브리드 후보 노드 인출기 (Hybrid Candidate Retriever) [P0]
* **기능**:
  - Mac 로컬 볼트 내 기존 마크다운 파일들의 제목, H1/H2 목차, 핵심 태그를 메모리 인덱스에 캐싱.
  - 원문의 핵심 개념과 가장 연관성이 높은 후보 노드 3~5개를 선별.
  - **Ego-Subgraph 확장**: 선별된 각 후보 노드가 이미 연결하고 있는 1-hop 이웃 노드들의 목록까지 함께 번들링하여 검증기에 공급.

### FR-4. 5대 인지 원형 및 k-hop 비판관 검증기 (Cognitive Critic Engine) [P0]
* **기능**:
  - 선별된 후보 노드에 대해 단순 유사도가 아닌 **5대 인지 원형** 적합성 판별:
    1. `CAUSED_BY` (인과)
    2. `PROVES` (실증 근거)
    3. `ADAPTS_FROM` (차용 및 응용)
    4. `CONTRASTS_WITH` (반론 및 대조)
    5. `PART_OF` (구성 및 계층)
  - **비판관 채점 룰(Critic Scoring)**:
    - 후보 노드의 본문 및 이웃 노드 맥락을 대조하여 0~100점 점수 산출.
    - **85점 이상**: 합당한 인과 관계 요약문과 함께 `[[노트명]] :: [원형] -> 사유` 승인.
    - **85점 미만 (Fallback)**: **억지 연결 거부**. 어떤 노드와도 링크하지 않고 오직 상위 `[[MOC_XXX]]`에만 단독 배치(고립 허용 예외 발동).

### FR-5. 시간적 관점 적층기 (Temporal Perspective Stacker) [P1]
* **기능**:
  - 새로 작성되는 노트가 과거의 기존 경험 노트와 동일한 주제를 다루고 있을 경우 감지.
  - 과거 노트를 직접 덮어쓰지(Overwrite) 않고, 원본 과거 노트 하단에 `> [!NOTE] ⏳ 관점 적층 (Perspective Stack)` 블록을 추가 커밋.
  - 신규 노트에는 `[[과거노트]] :: [REINTERPRETED_AS] -> 재해석 내용` 링크 생성.

### FR-6. 마크다운 생성 및 볼트 커미터 (Vault Committer) [P0]
* **기능**:
  - 수집된 모든 메타데이터와 원문을 결합하여 `00_헌법.md` 호환 마크다운 파일 생성.
  - `> [!QUOTE] 원문 맥락 창고`에 사용자 입력 원본 무손실 보존.
  - 지정된 경로(Google Drive 동기화 로컬 폴더)에 원자적(Atomic) 파일 I/O 실행.

### FR-7. 야간 무의식 기억 공고화 데몬 (The Dreaming Daemon) [P1]
* **기능**:
  - 매일 새벽 02:00 ~ 05:00 유휴 시간대 작동.
  - **1단계 (휴리스틱 프루닝 - O(1) 비용)**: 서로 다른 MOC에 속하며 그래프 거리가 먼 이종 노드 쌍을 5~10개 샘플링.
  - **2단계 (멀티에이전트 토론 - LLM)**: 옹호관(은유/공통 메커니즘 제시) vs 비판관(논리적 비약 공격) 3턴 설전 시뮬레이션.
  - **3단계 (합성 브릿지 생성)**: 토론 평가 90점 이상 획득 시 새로운 `합성_XXX.md` 초안 생성 및 아침 08:00 알림 큐에 적재.

---

## 4. 비기능 요구사항 (Non-Functional Requirements - NFR)

1. **지연 시간 (Latency)**:
   - 모바일 인테이크 요청 후 최종 마크다운 생성까지 총 소요 시간은 **5초 이내**여야 함.
   - LLM 호출 횟수는 실시간 파이프라인에서 최대 2회(1차 생성기 + Critic 검증기)로 제한.
2. **비용 및 토큰 최적화 (Cost Control)**:
   - Critic 검증 시 볼트 전체를 읽지 않고, 인덱서가 뽑은 Top-3 노드의 H1/H2 및 핵심 요약부만 주입하여 프롬프트 토큰을 4K 이하로 억제.
3. **로컬 주권 및 무결성 (Data Integrity)**:
   - 외부 서버에 마크다운 파일이 보관되지 않으며, 모든 파일 I/O는 로컬 디스크(`경험정리/` 및 `Obsidian/`)에서만 발생.
   - 파일 쓰기 충돌 방지를 위해 파일 생성 전 중복 파일명 자동 넘버링(`_v2`) 처리.

---

## 5. 엣지 케이스 및 실패 모드 분석 (Failure Modes & Mitigations)

| 실패 시나리오 | 발생 원인 | 시스템 대응책 (Mitigation) |
| :--- | :--- | :--- |
| **과잉 검열로 인한 고립 노트 양산** | Critic 비판관의 기준이 너무 높아 유의미한 연결도 전부 85점 미만으로 탈락시킴 | 85점 탈락 노드도 상위 `[[MOC_...]]` 링크는 필수 부여하여 최소한의 탐색 경로 보장. 주간 리포트에서 탈락 링크 로그 검토. |
| **원문 스크래핑 실패 (Paywall/JS)** | 보안 차단 뉴스 사이트, 로그인 필요 페이지 | 스크래핑 실패 시 사용자에게 즉시 에러를 뱉지 않고 URL 자체와 사용자가 입력한 코멘트만으로 1차 노트를 생성하고 알림. |
| **야간 드리밍 데몬의 토큰 폭식** | 조합 알고리즘 오류로 수백 개 노드를 무차별 토론에 진입시킴 | 하룻밤 최대 토론 횟수(Max Debates)를 **5회**로 하드코딩 상한선(Safety Cap) 설정. |
| **시간적 관점 오분류** | 과거의 전혀 다른 사건을 같은 사건으로 착각하여 엉뚱한 노드에 적층 콜아웃을 덧칠함 | 사용자의 명시적 키워드(예: "이전에 겪었던 ~ 재해석")가 있거나, 프로젝트 고유명사가 100% 일치할 때만 적층 트리거. |

---

## 6. 백엔드 작업 분할 구조 (WBS & Implementation Roadmap)

```
[Phase 4 / Sprint 2: Core Cognitive Pipeline]
 ├── Task 2.1: Blackboard State 인터페이스 및 Pydantic 스키마 정의
 ├── Task 2.2: Local Vault TOC/Heading 인덱서 및 Ego-Graph 추출기
 ├── Task 2.3: 5대 인지 원형 판별 및 85점 Critic 모듈 구현
 ├── Task 2.4: MOC 격리 Fallback 및 Constitutional Generator 통합
 └── Task 2.5: Perspective Stacking (과거 노트 Callout 주입기) 구현

[Phase 5 / Sprint 3: The Dreaming Daemon Engine]
 ├── Task 3.1: 야간 크론 스케줄러 및 그래프 거리 계산기
 ├── Task 3.2: Multi-Agent Debate 엔진 (Advocate vs Critic 3-Turn)
 └── Task 3.3: Morning Serendipity 알림 디스패처 (Telegram 연동)
```
