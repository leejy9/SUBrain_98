# [PRD] SUBrain_98 대화형 맥락 튜닝 작업대 & 독립 지식 관측창 명세서
# (Conversational Triage Workbench & Observability Graph Canvas)

> **Document Status**: Approved (Architecture Invariant)  
> **Author**: leejy9 x Antigravity (`prd-architect`)  
> **Target Release**: Phase 4 / Sprint 3  
> **Core Principle**: *"그래프는 작업대가 아니라 사후 관측창이며, 지식의 연결은 시각적 점잇기가 아니라 AI 비판관과의 대화형 합의(Conversational Alignment)에서 완성된다."*

---

## 1. Problem Definition & Scope Boundaries

### 1.1 The Real Problem (해결하려는 진짜 문제)
1. **작업대와 관측창의 주객전도 (UI Spatial Bottleneck)**:
   * 현재 대시보드는 좁은 랩탑 뷰포트(1710x861) 안에서 어설픈 그래프와 개발자용 감사 체크리스트(LCS Diff, 85점 룰, 15자 경고)가 화면을 70% 이상 잠식하고 있습니다.
   * 그 결과, 사용자가 정작 **"이 지식에 내 고유한 관점과 맥락을 얹는 집중 작업 공간"**이 극도로 위축되어 심각한 인지 피로를 유발합니다.
2. **'무맥락 요약의 함정'과 활용 단계의 오류 과다**:
   * 모바일에서 링크를 캡처하면 AI가 표면적 텍스트만 요약해둘 뿐, 정작 실무 기획이나 의사결정에 꺼내 쓰려 할 때 **"내가 당시 왜 이 정보에 주목했는지"** 주관적 의도가 누락되어 왜곡과 오류가 폭증합니다.
3. **컨텍스트 윈도우 휘발성과 매번 반복되는 원점 설명 피로**:
   * AI 대화창마다 내 배경과 상황을 매번 처음부터 설명해야 하고, 대화가 길어지면 메모리가 지워집니다. AI의 일시적 RAM에 맥락을 맡기지 않고, **영구적이고 구조화된 로컬 지식 DB(Context-as-a-Database)로 내 맥락을 오프로딩**할 인터페이스가 필요합니다.
4. **인간 발화 단독 분류의 취약성 (Edge Case)**:
   * "내가 말을 얹었는가"만으로 카드의 중요도를 판별하면, 바쁜 날 말을 못 얹은 핵심 기사가 유실(False Negative)되거나 사소한 잡담이 과대평가(False Positive)되는 맹점이 존재합니다.

### 1.2 Core Value Proposition (핵심 가치 제안)
* **Before**: 좁은 화면에서 텍스트와 그래프가 충돌하며, AI의 요약본을 수동으로 감시하고 수정하는 딱딱한 품질 검사대.
* **After**: 
  1. 화면 전체를 넓게 쓰는 **1:1 대화형 맥락 튜닝 작업대**에서 AI 악마의 대변인과 논쟁하며 나의 암묵지를 주입.
  2. 기계적 보조 알고리즘(정보 밀도, 볼트 근접도)이 카드의 가치를 1차 판정.
  3. 합의된 시냅스는 독립된 **풀스크린 지식 관측창**에서 네온 불(`New!`)을 밝히고 참조 빈도에 따라 온도로 시각화.

### 1.3 Goals & Success Metrics (KPI)
* **맥락 주입 소요 시간**: 카드 1건당 내 관점을 대화로 털어놓고 헌법 본문에 반영하기까지 **45초 이내 완료**.
* **대화 피로 방어율 (Two-Speed Triage)**: 단순 뉴스는 `[⚡ 즉시 승인]` 원클릭으로 2초 내 처리하여 인박스 적체 0건 유지.
* **아첨 환각 차단율**: AI가 사용자 가설의 한계점과 기존 볼트 노드와의 충돌을 최소 1회 이상 검증하는 **비판관 하네스 통과율 100%**.

### 1.4 Non-Goals (명시적 비목표 - Out of Scope)
1. **작업대 화면 내부의 상시 미니 그래프 금지**: 메인 작업대 컬럼에 2D/3D 그래프를 억지로 끼워 넣지 않는다. (상단 탭으로 완전 분리).
2. **모든 카드의 강제 대화 금지**: 정보 밀도가 낮은 일반 뉴스는 대화창을 거치지 않고 원클릭으로 10_Notes에 직행할 수 있어야 한다.
3. **AI의 무조건적 동조(Yes-Man) 금지**: 사용자의 직관을 칭찬하는 데 토큰을 낭비하지 않고, 기존 볼트와의 인과적 충돌 지점을 먼저 찌른다.
4. **복잡한 외부 소셜 네트워크 연동 배제**: 지식의 판매/공유 마켓플레이스는 Phase 3 로드맵으로 격리하며, 본 스펙에서는 로컬 완결형 작업대에 집중한다.

---

## 2. Multi-Persona Perspectives & User Journey

| 페르소나 | 주요 목표 | 치명적 페인포인트 | 인수 조건 (Acceptance Criteria) |
| :--- | :--- | :--- | :--- |
| **전략가 (Strategist)** | 도메인 불변 메커니즘 추출 & 의사결정 시뮬레이션 | 얕은 단어 요약, N=1 성공 서사의 과적합 | CCIA 4단계 사슬 기반 인과 분해 및 다중 케이스 집적 구조 보존 |
| **빌더 (Architect)** | 무결성 불변식, 로컬 단일 관문 I/O, 무손실 저널링 | WebSocket 끊김, 디스크 쓰기 충돌, 비동기 레이턴시 | `vault_io.safe_write` 단일 관문 준수, SHA-256 해시 검증, 오프라인 롱폴링 큐 완벽 복원 |
| **사용자 (Practitioner)** | 제로 프릭션 캡처, 대화 피로 없는 매끄러운 튜닝 | 매번 챗봇에게 내 상황 설명하기, 주말에 쌓인 인박스 피로 | 모바일 1초 발사 ➔ 데스크톱 2단 콕핏에서 1줄 대화 튜닝 ➔ 풀스크린 캔버스 New! 발광 조망 |

### End-to-End 사용자 여정 (User Journey)
```text
[1. 모바일 찰나의 포착]
웹서핑 중 기사/카드뉴스 발견 ➔ Telegram 공유 (Mac 꺼져 있어도 텔레그램 서버 롱폴링 대기)
   │
   ▼ (Mac 부팅 및 데몬 가동 시 자동 인출)
[2. 백그라운드 보조 스코어링]
daemon/scoring_engine.py 가동
➔ 정보 밀도(수치/용어), 볼트 근접도(82개 노드 연관성), 인간 개입 여부 3대 지표 산출
➔ 카드 헤더에 [밀도 92점 | 🧠 딥 튜닝 권장] 또는 [밀도 40점 | ⚡ 즉시 승인 권장] 배지 부여
   │
   ▼ (사용자가 여유로운 시간에 대시보드 접속: http://127.0.0.1:8765)
[3. 2단 대화형 작업대 (Workbench)]
좌측 큐에서 카드 클릭 (화면 분할: 좌 380px 원천 소스 / 우 1300px 작업대)
   ├─ A. 일반 뉴스 ➔ 상단 [⚡ 즉시 승인] 원클릭 ➔ 10_Notes/ 직행 (2초)
   └─ B. 핵심 인사이트 ➔ 하단 맥락 입력창: "난 이 정보가 B2B 영업 마찰을 줄이는 관점에서 중요하다고 봐"
         │
         ▼
[4. 악마의 대변인(Devil's Advocate) 하네스 대화]
AI: "사용자님의 관점은 타당하나, 기존 노트 [[경험_고객불신전환]]의 전제와 충돌합니다. 이를 상쇄할 근거가 있습니까?"
사용자: "이 케이스는 초기 무료 PoC 단계라 고객 리스크가 0이라는 전제가 깔려 있어."
AI: "납득되었습니다. 전제조건을 반영하여 [[지식_초기PoC전략]]으로 재정의하고 [[경험_고객불신전환]]과 [ADAPTS_FROM]으로 연결합니다."
   │
   ▼
[5. 원클릭 승인 & 볼트 영구 편입]
사용자가 [✓ 최종 반영 및 영구 저장] 클릭 ➔ `vault_io.move_from_inbox` 실행 ➔ `10_Notes/` 안착
   │
   ▼
[6. 독립 탭: 지식 그래프 관측창 (Graph Canvas)]
상단 탭 [🌐 지식 그래프] 클릭 ➔ 광활한 풀스크린 캔버스 전환
➔ 방금 추가된 노드가 네온 골드 펄스(New!)로 반짝이고, 참조 빈도 카운트가 갱신되어 크기가 커짐.
```

---

## 3. Functional Requirements & Ontology Rules

### F1. 대시보드 2단 대화형 작업대 UI (`dashboard_prototype.html`)
* **레이아웃 명세**:
  * **좌측 인박스 & 원천 패널 (너비 380px 고정)**:
    * 상단: 인박스 카드 리스트 (스코어링 배지 포함).
    * 하단: 선택된 카드의 '원천 소스 URL' 및 캡처 당시의 '날것의 메모/음성 텍스트' 무손실 뷰어.
  * **우측 맥락 튜닝 작업대 (가변 너비, 남은 전체 폭 ~1300px)**:
    * 상단 바: 파일명 식별자, 분류 배지, **[⚡ 즉시 승인]**, **[✓ 최종 반영 및 영구 저장]** 액션 버튼.
    * 중단 (리더 뷰): 헌법 CCIA 인과 사슬 및 한 줄 요약이 담긴 마크다운 프리뷰.
    * 하단 (대화 콕핏): **대화형 맥락 튜닝 채팅창 (Interactive Context Chat)**.
* **Gherkin Acceptance Criteria**:
  * `GIVEN` 사용자가 대시보드 인박스에서 카드를 선택했을 때,
  * `WHEN` 우측 작업대가 열리면,
  * `THEN` 복잡한 감사 체크리스트 대신 마크다운 본문과 맥락 주입 채팅창이 넓고 시원하게 렌더링되어야 한다.

### F2. 3대 보조 스코어링 엔진 (`daemon/scoring_engine.py`)
* **3대 지표 산출 알고리즘**:
  1. `information_density` (0~100): 
     * 원문 텍스트 내 수치(%, 원, 달러, 연도, 배수) 및 전문 어휘 비율 측정.
  2. `vault_proximity` (0~100): 
     * 기존 옵시디언 82개 영구 노드 및 MOC 키워드와의 TF-IDF / BM25 근접도 점수.
  3. `human_intent_boost` (0 or 20): 
     * 캡처 당시 사용자가 1자 이상의 텍스트/음성 메모를 동봉했으면 +20점 부스트.
* **종합 추천 상태 판정**:
  * `total_score >= 75`: `DEEP_TUNE_RECOMMENDED` (보라색 배지: 🧠 딥 튜닝 권장)
  * `total_score < 75`: `FAST_TRACK_ELIGIBLE` (회색 배지: ⚡ 즉시 승인 가능)

### F3. 악마의 대변인(Devil's Advocate) 대화 하네스 (`daemon/agent_core.py`)
* **프롬프트 하네스 불변식**:
  * AI는 사용자의 발화에 무조건 칭찬하거나 아첨(Sycophancy)하지 않는다.
  * 사용자의 입력이 들어오면 기존 볼트 노드 목록(`vault_nodes_summary`)을 스캔하여, **반드시 1개 이상의 반론, 경계 조건, 혹은 충돌 가능성을 질문**한다.
  * 사용자가 재반박하여 납득되면, 대화 내용을 본문의 `## 1. 한 줄 요약`, `## CCIA 인과 사슬`, `## 4. 기록 시점의 중요성(Why It Mattered Then)`에 즉각 반영한 수정 Diff Proposal을 반환한다.

### F4. 독립형 풀스크린 지식 관측창 (`dashboard_graph.html` or Graph Tab)
* **네비게이션**: 상단 글로벌 헤더에 `[ 📝 작업대 (Workbench) ]` | `[ 🌐 지식 그래프 (Graph View) ]` 탭 스위처 제공.
* **풀스크린 캔버스**: 1700px 전체 화면을 활용한 D3.js 기반 Force-Directed 노드 링크 그래프.
* **지식 생애주기 매트 미니멀 시각화 (형광/네온 0%)**:
  * `신규 노드(24h 이내)`: 눈부신 네온/펄스를 일체 배제하고, 차분한 **이중 링 윤곽선 (Double Ring Outline)**으로 정갈하게 식별.
  * `시간대별 뮤트 톤 코딩`:
    * 7일 이내: 차분한 웜 세이지/카멜 (`#8fa876` / `#c4a482`)
    * 30일 이내: 안정된 슬레이트 그레이 (`#717b8a`)
    * 90일 이상: 은은한 옅은 애쉬 그레이 (`#454d5a`, opacity 40%)
  * `1-hop 인터랙티브 포커스`:
    * 평소에는 모든 엣지가 옅은 선(opacity 0.2)으로 배경에 정갈하게 머묾.
    * 노드 호버 시, 해당 노드와 직접 연결된 1촌(1-hop) 이웃 노드와 링크만 선명해지고 나머지는 부드럽게 감쇄되어 관계망 직관성 극대화.
* **참조 빈도 가중치**:
  * 프론트매터의 `referenced_count` 수치에 비례하여 노드 반지름(r = 5 + log2(referenced_count + 1) * 3) 동적 렌더링.

### F5. 오프라인 롱폴링 큐잉 및 연속 인테이크 방어 (`daemon/telegram_bot.py`)
* Mac이 꺼져 있는 동안 텔레그램 서버에 적체된 메시지는, 데몬 기동 즉시 `getUpdates`를 통해 타임스탬프 순서대로 순차 수신.
* 브라우저 크롤링 및 Gemini OCR 처리 중 동시성 충돌을 방지하기 위해 `asyncio.Lock()` 기반의 순차 인테이크 큐 보장.

---

## 4. Technical Architecture & Data Contracts

### 4.1 WebSocket / HTTP 이벤트 계약 (EventBridge Contract)

```typescript
// 1. 맥락 튜닝 대화 요청 (Client -> Server)
interface ContextTuneRequest {
  type: "CONTEXT_TUNE_CHAT";
  task_id: string;
  user_message: string;
  chat_history: Array<{ role: "user" | "assistant"; content: string }>;
}

// 2. 맥락 튜닝 응답 및 본문 제안 (Server -> Client)
interface ContextTuneResponse {
  type: "CONTEXT_TUNE_REPLY";
  task_id: string;
  assistant_reply: string;      // 악마의 대변인 반론 또는 납득 답변
  proposed_markdown?: string;    // 사용자 맥락이 반영된 최신 마크다운 본문
  proposed_links?: Array<{ target: string; archetype: string; reason: string }>;
}

// 3. 3대 스코어링 메타데이터 (TaskCard에 주입)
interface IngestScoreMetadata {
  information_density: number;  // 0~100
  vault_proximity: number;      // 0~100
  human_intent_boost: number;   // 0 or 20
  total_score: number;          // 0~100
  triage_recommendation: "DEEP_TUNE_RECOMMENDED" | "FAST_TRACK_ELIGIBLE";
}
```

### 4.2 파일시스템 및 프론트매터 불변식 (Single Source of Truth)

모든 승격된 영구 노트(`.md`)는 다음 메타데이터를 유지합니다:

```yaml
---
aliases: ["핵심 요약"]
tags: ["#permanent", "#지식/도메인"]
date: 2026-10-13
source_date: 2026-10-12
captured_at: "2026-10-13 16:15:00"
status: 완료
type: Permanent
moc: "[[MOC_도메인]]"
referenced_count: 1
last_referenced_at: "2026-10-13 16:15:00"
---
```

---

## 5. PIV Execution Plan (Task Breakdown)

### Phase 1: 대시보드 메인 2단 대화형 작업대 UI 개편
- [x] **Task 1.1**: `dashboard_prototype.html`의 거추장스러운 상시 감사 패널/LCS Diff를 모달로 숨기고, 좌(380px 원천 소스) / 우(1300px 작업대) 2단 반응형 그리드 구축.
- [x] **Task 1.2**: 우측 작업대 하단에 대화형 맥락 주입 컴포넌트(`ContextTuneChat`) UI 및 메시지 렌더러 삽입.
- [x] **Task 1.3**: 상단 바에 `[⚡ 즉시 승인]`(패스트 트랙) 버튼 및 글로벌 헤더 탭 스위처(`[작업대] | [지식 그래프]`) 신설.
- [x] **Task 1.4**: E2E 브라우저 검증: 1710x861 해상도에서 시원하게 렌더링되는 레이아웃 스크린샷 검증.

### Phase 2: AI 비판관 대화 하네스 & 3대 보조 스코어링 엔진
- [x] **Task 2.1**: `daemon/scoring_engine.py` 신설 — 정보 밀도(정량 수치/어휘), 볼트 근접도(BM25), 인간 개입 부스트 계산 로직 구현 및 단위 테스트.
- [x] **Task 2.2**: `daemon/event_bridge.py`에 `CONTEXT_TUNE_CHAT` 웹소켓 핸들러 등록.
- [x] **Task 2.3**: `daemon/agent_core.py`에 악마의 대변인 프롬프트 체인 구축 — 사용자 발화 수신 시 기존 볼트 노드 충돌 검증 및 대화형 제안 생성.
- [x] **Task 2.4**: 대화 합의 시 마크다운 본문 자동 재구성 및 `vault_io.safe_write` 연동 검증.

### Phase 3: 독립형 풀스크린 지식 관측창 (Graph Canvas)
- [x] **Task 3.1**: `dashboard_prototype.html` 내 탭 전환 로직 구축 (`#view-workbench` ↔ `#view-graph`).
- [x] **Task 3.2**: D3.js 기반 풀스크린 캔버스 렌더러 구현 (82개 노드 및 위키링크 엣지 연동).
- [x] **Task 3.3**: 신규 노드 정갈한 이중 링 윤곽선(`Double Ring`) 렌더링 및 생성 시기별 뮤트 톤 코딩(웜 세이지 ➔ 슬레이트 그레이 ➔ 애쉬 그레이) + 1-hop 호버 포커스 적용.
- [x] **Task 3.4**: 프론트매터 `referenced_count` 기반 동적 노드 반지름 렌더링 및 클릭 시 상세 보기 연동.

### Phase 4: 모바일 비동기 오프라인 큐잉 및 실전 E2E 안정화
- [x] **Task 4.1**: `daemon/telegram_bot.py` 롱폴링 오프라인 버퍼링 시뮬레이션 테스트 (데몬 다운 ➔ 메시지 3건 발송 ➔ 기동 ➔ 전량 수신 검증).
- [x] **Task 4.2**: `asyncio.Lock`을 통한 동시 인테이크 파이프라인 무결성 확보.
- [x] **Task 4.3**: 실제 모바일 텔레그램 ➔ 대시보드 2단 작업대 대화 튜닝 ➔ 옵시디언 영구 저장 ➔ 그래프 New! 발광 E2E 전체 사이클 통과 확인.

---

## 6. Critical Trade-offs & Risk Mitigation (비판적 자가 감사)

| Risk / Edge Case | Likelihood | Impact | Mitigation Strategy (대응 설계) |
| :--- | :---: | :---: | :--- |
| **1. 대화 피로 (Chat Fatigue)** | High | High | **Two-Speed Triage 도입**: 75점 미만 일반 뉴스는 `[⚡ 즉시 승인]`으로 2초 내 처리. 딥 튜닝 권장 카드만 대화창 활성화. |
| **2. 아첨 본능 (Sycophancy)** | Medium | High | **악마의 대변인 하네스 강제**: AI 프롬프트에 "사용자 가설에 대한 최소 1개 반론 및 충돌 지점 질문 의무화" 규율 박제. |
| **3. 거시적 시야 결핍 (Local Myopia)** | Medium | Medium | **독립 탭 풀스크린 관측창 분리**: 좁은 곳에 욱여넣지 않고, 원클릭으로 1700px 광활한 캔버스에서 신규 시냅스 발광 조망. |
| **4. 연쇄 레이턴시 (Cascading Latency)** | Low | Medium | **비동기 듀얼 채널**: 모바일 수집은 2초 내 완료되고, 무거운 튜닝 대화는 PC 대시보드에서 필요할 때만 비동기로 실행. |

---

## 7. Next Immediate Action
Phase 1부터 Phase 4까지 전 공정 구현 및 E2E 실측 검증 완료. 일상 운영 및 모바일 텔레그램 인테이크와 지식 그래프 관측 상시 가동 중.

