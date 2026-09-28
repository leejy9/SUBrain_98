# Subrain_98 시스템 아키텍처 설계서 (System Architecture Specification)

> **문서 버전**: v2.0 (Cognitive & Temporal Neuro-Symbolic Architecture)  
> **최종 수정일**: 2026-09-18  
> **핵심 철학**: 무마찰 캡처, 헌법적 엄격성, 의미론적 연결(5 Cognitive Primitives), 시간적 관점 적층(Perspective Stacking), 야간 무의식 합성(The Dreaming Daemon)

---

## 1. 하이브리드 종합 시스템 아키텍처 (Macro Architecture)

```mermaid
flowchart TB
    subgraph INGESTION ["1. Ingestion Layer (모바일 무마찰 포획)"]
        G[Galaxy Android Mobile] -->|Share Sheet| TG[Telegram Bot Client]
        G -.->|Web Share Target API| PWA[Standalone Mobile PWA]
        MAC[Mac Desktop Browser / Local] -->|Drag & Drop / CLI| LOCAL_IN[Local Ingest Watcher]
    end

    subgraph GATEWAY ["2. Event & Agent Gateway Layer"]
        TG & PWA & LOCAL_IN --> GATE[Agent Gateway Daemon / Poller]
        GATE --> QUEUE[(Active Event Buffer)]
    end

    subgraph BRAIN ["3. Dual-Engine Cognitive Brain (인지 두뇌)"]
        direction TB
        
        subgraph REALTIME_PIPE ["A. Realtime Neuro-Symbolic Ingestion Pipeline"]
            P1[1. Scrape & Grounding Engine] --> P2[2. Constitutional Structurer: 00_헌법.md]
            P2 --> P3[3. Candidate Retriever: Hybrid Index]
            P3 --> P4[4. Cognitive Primitives Classifier: 5대 연결 원형]
            P4 --> P5{5. k-hop Ego Critic: 비판적 검증관}
            P5 -->|Score >= 85| P6[Semantic Bridge Link: [[노트]] + 인과/맥락]
            P5 -->|Score < 85: 억지연결 거부| P7[Fallback Isolation: 상위 MOC에만 격리]
            P6 & P7 --> P8[Temporal Perspective Stacker: REINTERPRETED_AS]
        end

        subgraph DREAMING_DAEMON ["B. The Dreaming Daemon (야간 무의식 기억 공고화)"]
            D1[Nightly Idle Scheduler: 02:00~05:00] --> D2[Cross-Domain Distant Sampler]
            D2 --> D3[Multi-Agent Debate: 옹호관 vs 비판관]
            D3 --> D4{Serendipity Validator: 점수 >= 90?}
            D4 -->|통과| D5[Generate Synthetic Insight / Synthesis Bridge]
            D4 -->|탈락| D6[Discard to Log]
            D5 --> D7[Morning Serendipity Card 배달]
        end
    end

    subgraph VAULT ["4. Sovereign Knowledge Vault (로컬 지식 저장소)"]
        P8 & D5 --> MD_WRITER[Obsidian Markdown Engine]
        MD_WRITER --> V_INBOX["00_Inbox / 10_Notes (Atomic)"]
        MD_WRITER --> V_MOC["20_MOC (상위 지도)"]
        MD_WRITER --> V_BRIDGE["30_Bridges (개념 간 연결 가교)"]
        MD_WRITER --> V_META["99_Meta / Project Logs"]
        
        V_INBOX & V_MOC & V_BRIDGE --> G_DRIVE[Google Drive 실시간 동기화: Mac ↔ 모바일]
        V_INBOX & V_MOC & V_BRIDGE --> LOCAL_INDEX[(Local SQLite / Vector & TOC Index)]
    end

    subgraph SURFACES ["5. Interactive Control & Observation Surface"]
        D7 & P8 --> TG_NOTI[Telegram Interactive Callback Card]
        TG_NOTI -->|승인 / 수정 / 거절| GATE
        LOCAL_INDEX --> WEB_DASH[Subrain Web Dashboard: Next.js + 3D Force Graph]
        WEB_DASH --> AUDIT_VIEW[Reasoning Trail & Perspective Timeline]
    end
```

---

## 2. 핵심 계층 및 컴포넌트 상세 명세 (Component Breakdown)

### 2.1 [입력단] 모바일 무마찰 포획 계층 (Mobile Ingestion Layer)
* **목표**: 3초 이내 인지적 마찰(Friction) 제로로 생각, 기사, PDF, 영상을 볼트로 투입.
* **컴포넌트 구성**:
  1. **Telegram Ingestion Bot (`telegram_bot.py`)**:
     - 안드로이드 기본 '공유하기' 시트에서 텔레그램 봇으로 전송.
     - 4-Button Quick Action (`[경험/커리어]`, `[지식/원리]`, `[기업/산업]`, `[아이디어/단상]`).
     - 음성 메시지(Whisper 자동 전사), 스크린샷 이미지(Gemini Multimodal OCR), URL 원문 자동 파싱.
  2. **Zero-Loss Scraping Engine**:
     - 트위터/X, 뉴스, 블로그 본문 파싱 + Paywall 및 스크립트 기반 기사 정제.
     - 사용자 입력 원문/발췌문은 마크다운 내 `> [!QUOTE] 원문 맥락 창고`로 100% 무손실 보존.

---

### 2.2 [두뇌 1] 실시간 신경-기호 파이프라인 (Realtime Neuro-Symbolic Ingestion Pipeline)
* **실행 환경**: Mac 로컬 상주 백그라운드 프로세스 (Python Daemon).
* **단계별 처리 엔진**:
  1. **Constitutional Structurer (헌법적 구조화기)**:
     - `00_헌법.md` 프롬프트를 주입하여 엄격한 YAML Frontmatter, H1/H2 계층, 15자 이내 간결한 파일명 생성.
  2. **Cognitive Primitives Classifier (5대 연결 원형 판별기)**:
     - 두 노드 간의 관계를 단순 '언급'이 아닌 명확한 인지적 의미로 규정.
     - **5대 연결 원형**:
       - `CAUSED_BY` (인과 관계: A 현상의 원인이 B)
       - `PROVES` / `EVIDENCES` (실증 근거: A 주장의 실제 증거가 B)
       - `ADAPTS_FROM` (차용·응용: B 도메인의 원리를 A에 적용)
       - `CONTRASTS_WITH` (반론·대조: A의 전제와 B의 사실이 충돌)
       - `PART_OF` (구성·계층: A가 B 체계의 하위 구성요소)
  3. **The Critic Agent & k-hop Ego Subgraph Validator (비판적 검증관)**:
     - **문제의식**: 단순 키워드 유사도에 기반한 억지 연결(예: 외인 주식 매도에 반려식물트렌드 연결) 원천 차단.
     - **검증 프로세스**:
       - 타겟 후보 노드 본문뿐 아니라 그 노드와 이미 연결된 1~2 hop 이웃 노드(Ego-Graph)의 맥락까지 함께 인출.
       - 연결 유효성 스코어링(0~100점).
       - **85점 이상**: 합당한 인과/맥락 설명과 함께 `[[노트명]] (연결 이유 및 원형)` 생성.
       - **85점 미만 (Fallback)**: 억지 연결을 전면 포기하고 상위 주제 `[[MOC_XXX]]`에만 단독 배치(헌법 고립 방지 예외 조항 발동).
  4. **Temporal Perspective Stacker (시간적 관점 적층기)**:
     - 과거 신입사원 시절 기록한 경험과 현재 시니어 시절의 새로운 인사이트가 충돌할 때, 과거 노트를 파괴적으로 수정(Overwrite)하지 않음.
     - `REINTERPRETED_AS` 링크를 형성하고, 원본 노트 하단에 `> [!NOTE] ⏳ 시간적 관점 적층 (Perspective Stacking)` Callout을 덧붙여 지식의 진화 궤적을 보존.

---

### 2.3 [두뇌 2] 야간 무의식 기억 공고화 (The Dreaming Daemon)
* **작동 주기**: 매일 새벽 02:00 ~ 05:00 (시스템 유휴 시간) 또는 사용자 수동 호출.
* **동작 원리 (인간 수면 중 기억 통합 모사)**:
  1. **Distant Domain Sampling**: 볼트 내에서 서로 다른 MOC나 거리가 먼 클러스터에 위치한 노드 쌍(예: "제조 공정 센서 이상 탐지" ↔ "고객 이탈 심리 분석")을 무작위 또는 가설 기반 추출.
  2. **Multi-Agent Debate (인사이트 공방전)**:
     - *Advocate Agent*: 두 노드 간의 숨겨진 공통 메커니즘, 비유, 창의적 결합 가능성을 제안.
     - *Critic Agent*: 표면적 어휘 일치나 궤변을 공격하고 엄격한 논리적 정합성 검증.
  3. **Synthetic Bridge Note Generation**:
     - 토론을 통과한(90점 이상) 진정한 통찰에 대해 새로운 합성 브릿지 노트(`합성_XXX.md`) 초안 생성.
  4. **Morning Serendipity Card**:
     - 아침 08:00에 텔레그램으로 "밤사이 뇌가 발견한 뜻밖의 연결" 카드를 사용자에게 배달하여 승인 여부 질의.

---

### 2.4 [저장소] 주권적 로컬 볼트 계층 (Sovereign Knowledge Vault)
* **철학**: 플랫폼 종속 없는 순수 로컬 마크다운(Plain Markdown) + Git/Drive 소유권.
* **디렉토리 구조**:
  - `00_Inbox/`: 정제 전 임시 캡처 및 에이전트 초안 대기열.
  - `10_Notes/`: 헌법 준수 원자적 지식 및 경험 노트 (STAR, 메커니즘).
  - `20_MOC/`: 주제별 지식 지도 (Map of Content).
  - `30_Bridges/`: 야간 데몬 또는 심층 추론이 만들어낸 이종 개념 간 가교 노트.
  - `99_Meta/`: 헌법(`00_헌법.md`), 프롬프트 템플릿, 프로젝트 감사 로그(`00_PROJECT_LOG.md`).
* **동기화 파이프라인**:
  - Mac 로컬 디스크 ↔ Google Drive Desktop 클라이언트 실시간 미러링 ↔ 갤럭시 안드로이드 상호 동기화.

---

### 2.5 [관제 및 UI] 대시보드 및 피드백 루프 (Interaction Surface)
* **Telegram Feedback Loop**:
  - 캡처 즉시 에이전트가 제안하는 [제목 / 요약 / 연결 후보 / 인과 원형]을 인라인 카드 형태로 전송.
  - 사용자는 원클릭 버튼(`[승인 및 저장]`, `[연결 제거]`, `[추가 코멘트]`)으로 개입.
* **Next.js Web Dashboard (관제탑)**:
  - **Reasoning Stream**: 에이전트의 실시간 사고 판단(적용 헌법 조항, 비판관 채점표) 타임라인 뷰.
  - **Temporal Graph Canvas**: 2D/3D Force Graph 위에서 시간 축(Time Slider)을 움직여 관점의 적층과 지식망의 성장 과정을 시각화.
  - **Competency Radar**: `[[역량_...]]` 노드의 유기적 밀도 분석.

---

## 3. 데이터 스키마 및 프로토콜 규격

### 3.1 5대 인지 원형 링크 규격 (Markdown Semantic Syntax)
```markdown
## 🔗 인지적 연결망 (Cognitive Semantic Links)
- [[경험_국내증시_외인매도분석]] :: [CAUSED_BY] -> 환율 급등 및 거시경제 유동성 위축
- [[원리_시스템다이내믹스_피드백루프]] :: [ADAPTS_FROM] -> 공정 이상 탐지 알고리즘 구조에 시스템 피드백 모델 차용
- [[과거기록_2024_신입_프로젝트회고]] :: [REINTERPRETED_AS] -> 당시에는 단순 커뮤니케이션 실패로 보았으나, 현재 관점에서는 데이터 거버넌스 부재가 근본 원인이었음
```

### 3.2 시간적 관점 적층 Callout 규격 (Perspective Stacking Callout)
```markdown
> [!NOTE] ⏳ 관점 적층 (Perspective Stack: 2026-09-18)
> - **작성 시점**: 2024년 주니어 시절 (단기 과업 달성 중심)
> - **현재 시점 재해석**: 시니어 관점에서 볼 때 본 사건은 개별 테스크의 문제가 아닌 조직 내 사일로(Silo) 구조의 필연적 부산물이었음.
> - **연결된 후속 지식**: [[이론_조직사일로_타파모델]]
```

---

## 4. 단계별 구축 로드맵 (Roadmap)

| 단계 | 명칭 | 핵심 산출물 및 마일스톤 | 현 상태 |
| :--- | :--- | :--- | :--- |
| **Sprint 1** | Fast-Path Intake & Bot | 텔레그램 봇 데몬 가동, 모바일 캡처 수신, 헌법 준수 마크다운 생성 | **완료 (실기동 중)** |
| **Sprint 2** | Critic & Cognitive Primitives | 5대 인지 원형 분류기, k-hop 비판관 검증기(85점 룰), 억지연결 방지 Fallback | **설계 완료 / 개발 진행** |
| **Sprint 3** | The Dreaming Daemon | 야간 유휴 스케줄러, Multi-Agent 토론 엔진, 모닝 세렌디피티 카드 발송 | **아키텍처 확정** |
| **Sprint 4** | Web Control Canvas | Next.js 대시보드, 시간축 그래프 뷰어, 에이전트 사고 스트림 웹 UI | **설계 완료** |
