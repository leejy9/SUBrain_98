# SUBrain_98 — System Architecture & Interaction Spec for AI Designer

> **Version**: 1.0.0 (Production Blueprint)  
> **Target Audience**: AI Designer / Autonomous Frontend & UX Agent  
> **Platform**: Desktop Web SaaS Application (Standard Browser 1440px+ Viewport)  
> **Design Theme**: Atelier Monolith (Bright Off-white Canvas, Monochromatic Dark Text, Restrained Warm Amber/Beige Accents)

---

## 1. Project Overview & Vision
`SUBrain_98`은 분산된 외부 지식(arXiv 논문, Slack 웹훅, 로컬 Ingest, 웹 클리핑 등)을 실시간으로 수집하고, LLM의 다단계 추론(Chain-of-Thought)과 엄격한 엔티티 무결성 검증을 거쳐, 최종적으로 옵시디언(Obsidian) 형태의 Knowledge Graph 및 Markdown Vault로 커밋(Commit)하는 **지능형 지식 정제 & 그래프 관리 데스크톱 웹 플랫폼**입니다.

### Core Architecture Pipeline
```
[External Sources] -> (Webhooks, arXiv, Files)
       ↓
[Processing Queue] -> Real-time Ingestion & Step-by-Step Thinking Log
       ↓
[Staging & Review] -> Active Target Selection, Thinking Process Accordion, Integrity Checklist
       ↓
[Commit to Vault]  -> Obsidian-style Markdown File & Interactive Force-Directed Knowledge Graph
```

---

## 2. Global Navigation & Layout States

### 2.1 Top Global Navigation Bar
* **Brand Logo**: `SUBrain_98` (Minimal typography + live status dot `green`).
* **Route Tabs**:
  * `[대시보드]` (`#dashboard-view`): 실시간 큐 파이프라인, 추론 아코디언 검토, 엔티티 무결성 체크, 인라인 카드 코파일럿.
  * `[Graph]` (`#graph-view`): 3열 분할 볼트 탐색기(Tree) + 마크다운 뷰어(Editor) + 로컬 지식 그래프(Force-directed SVG).
* **Live System Metric**: Webhook latency status indicator (`Webhook Live 320ms`).
* **Global Search Box**: Omnibar search supporting `⌘K` keyboard shortcut with node/entity autocompletion.
* **Header Actions**:
  * `[+ 새 지식 인입 (URL / 파일)]`: Primary Action Button. 클릭 시 인입 모달/슬라이드오버 트리거.
  * System Settings (`gear` icon) & User Workspace profile status.

---

## 3. View 1: Intelligence Dashboard (`#dashboard-view`)

### 3.1 Top Summary Metric Strip (4 Cards)
1. **처리 파이프라인**: 활성 작업 수 및 파이프라인 상태 (예: `2 파이프라인 활성 중`).
2. **엔티티 무결성 지표**: 전체 검증 통과율 (예: `98.2% 합격 기준 상회`).
3. **검토 대기 인박스**: 보완 또는 사용자 승인이 필요한 항목 수 (예: `03 보완 대기 3건`).
4. **오늘 커밋 완료**: 지식화되어 그래프에 영구 반영된 문서 수 (예: `142 문서 지식화 완료`).

### 3.2 Left Column: Card Queue System (Width: 380px ~ 420px)
모든 정보 단위는 카드 형태로 규격화되어 관리됩니다.
* **Filter Tabs**: `전체 (6)` | `⚡ 처리 중` | `⚠️ 보완 필요 (3)` | `✓ 검토 완료 준비 (2)`.
* **Card Archetypes**:
  1. **Processing Card (실시간 처리 중)**:
     - 상태: 프로그레스 바(예: 78%), 처리 단계(`LLM 추론 및 파싱 중 (4/5단계)`).
     - Live Thinking Indicator: `> Thinking: 원문 추출 완료 → 태그 및 규칙 #04 검증 중...`.
     - 클릭 시: 우측 패널에 현재까지 생성된 실시간 토큰 스트림 및 추론 로그 출력.
  2. **Active / Staged Card (검토 대기 중 - Active State)**:
     - 상태 뱃지: `선택됨 (Active)`, 우선순위 및 규칙 불일치 경고 라벨.
     - 활성 보더 하이라이트(`border-neutral-900` / `ring-1`).
     - 클릭 시: 우측 메인 검토 화면(`Active Target`)과 1:1 바인딩 렌더링.
  3. **Ready to Commit Card (검토 완료)**:
     - 상태: 무결성 100% 검증 통과 뱃지.
     - 액션: 카드 내 즉시 커밋(`[즉시 Commit]`) 1클릭 버튼 제공.

### 3.3 Right Column: Active Target Review Workspace
선택된 카드의 세부 검토 및 인터랙티브 제어 공간입니다.
1. **Target Header**:
   - 고유 식별자: `#DOC-2502-01 // arXiv:2502.09112`.
   - LLM 엔진 버전: `Claude 3.5 Sonnet (v2)`.
   - 액션 바: `[임시보관 유지]` (Secondary) | `[⚡ DB로 최종 Commit]` (Primary Accent).
2. **Title & Frontmatter Metadata**:
   - 대제목, 연관 위키링크 태그(`[[Vector DB]]`, `[[Qdrant]]`, `[[HNSW]]`), 커스텀 태그(`+ 태그 추가`).
3. **Thinking Process Accordion (Gemini-Style Expandable Log)**:
   - 트리거: `✦ 모델 사고 과정 보기 (Thinking Process · 3.4초 소요)` 접기/펼치기 토글.
   - 구성 단계:
     * `Step 1 [원문 수집]`: PDF/문서 파싱, 코드/수식 블록 식별.
     * `Step 2 [규칙 대조]`: 전역 지식 규격 규칙(#RULE-FIN-COST-CHK 등) 대조 및 불일치 감지.
     * `Step 3 [엔티티 매핑]`: 기존 그래프 노드와의 연관도 및 유효 위키링크 계산.
     * `Step 4 [경고 생성]`: 사용자 개입이 필요한 수정 제안 및 승인 대기 플래그 등록.
4. **Extracted Synthesis (정제 마크다운 요약)**:
   - 토큰 통계(`Token Count: 482 / Reduction: 76%`).
   - 기술 요약 본문 및 수식/하이라이트.
5. **Warning & Resolution Box (경고 및 규칙 위반 대조)**:
   - 경고 배너: `⚠️ 이 부분은 확인이 필요해요 (LLM 제안 - #FIN-COST-CHK)`.
   - 수정 액션: `[직접 인라인 수정]` | `[규칙 자동 승인]` | `[경고 무시]`.
6. **Entity Integrity Checklist (무결성 검증 패널)**:
   - 전역 무결성 스코어 뱃지: `98.2% PASS`.
   - 4대 체크리스트:
     * `[✓] 위키링크 노드 유효성 (3/3 검증 통과)`
     * `[✓] 필수 프론트매터 속성 (date, author, domain 일치)`
     * `[!] 비용 산출식 최신 규격 (경고 1건 대기 중)`
     * `[✓] 중복 노드 충돌 검사 (충돌 없음)`
7. **Card Context Copilot Chat (하단 인라인 질의창)**:
   - 컨텍스트 고정 뱃지: `[현재 카드: #DOC-2502-01 참조 중] ✕`.
   - 퀵 액션 프롬프트 칩: `[🪄 규칙 자동 교정]` | `[🔗 위키링크 자동 보강]` | `[📄 3줄 핵심 압축]`.
   - 입력 필드: 프롬프트 질의, 전송 버튼(`Enter`), 개행(`Shift+Enter`).

---

## 4. View 2: Knowledge Graph & Vault View (`#graph-view`)

### 4.1 3-Column Split Layout
* **Left Column: Vault File Tree (Width: 260px ~ 300px)**:
  - 파일/폴더 트리 구조 (`_Attachments`, `00_Inbox`, `10_Notes`, `20_MOC`, `99_Meta`).
  - 태그 필터 검색창 (`tag:#도메인/상담` 등).
  - 하단 상태바: `Vault 통계: 78 노트 · 194 링크`.
* **Middle Column: Markdown Editor / Viewer (Width: Flexible 40% ~ 50%)**:
  - 마크다운 메타데이터(Frontmatter Property Table): `aliases`, `tags`, `date`, `status`, `type`, `역량`, `정량지표`.
  - 본문 렌더링: 구조화된 경험 분해(STAR 기법), 인라인 위키링크 하이라이트.
  - 뷰 전환 탭: `[문서만]` | `[스플릿 뷰]` | `[그래프만]`.
* **Right Column: Interactive Force-Directed Knowledge Graph (Width: Flexible 40% ~ 50%)**:
  - SVG/Canvas 기반 인터랙티브 지식 네트워크.
  - 깊이 컨트롤(`DEPTH 2`), 줌 인/아웃, 화면 맞춤(`Fit to Screen`), 물리 엔진 토글(`Physics ON`).
  - 활성 노드 하이라이트 및 연결 링크 시각화 (`IN 5 / OUT 3`).
  - 하단 선택된 노드 상세 팝업 패널 (`Active Hub Information`).

---

## 5. Interaction State Machine Specification

| Event / Trigger | Source Element | Action & State Transition | Target Result |
| :--- | :--- | :--- | :--- |
| **Tab Switch: Graph** | Top Nav `[Graph]` button | `activeTab = 'graph'` | `#dashboard-view` hides (`hidden`), `#graph-view` renders (`block`). |
| **Tab Switch: Dashboard** | Top Nav `[대시보드]` button | `activeTab = 'dashboard'` | `#graph-view` hides, `#dashboard-view` renders. |
| **Select Queue Card** | Left list item (`[data-card-id]`) | `activeCardId = targetId` | 이전 활성 카드 테두리 해제, 새 카드에 `ring-1 ring-neutral-900` 적용. 우측 `#active-target-container`의 ID/헤더/본문 교체. |
| **Toggle Accordion** | `[✦ 모델 사고 과정 보기]` header | `thinkingOpen = !thinkingOpen` | 아코디언 컨텐츠 블록 `max-height` 트랜지션 및 회전 화살표(`rotate-180`). |
| **Quick Prompt Click** | Copilot chip `[규칙 자동 교정]` | Input injection | 하단 입력창에 `"규칙 #FIN-COST-CHK 자동 교정 및 본문 반영해줘"` 자동 삽입. |
| **Graph Node Click** | SVG Circle Node | `activeNode = nodeId` | 선택된 노드 중심 하이라이트, 우측 하단 `선택된 노드 정보` 카드 데이터 갱신. |

---

## 6. Implementation Notes for AI Generator
1. **CSS Utility**: Tailwind CSS v3+ with zero arbitrary layout bugs. Use strict flex/grid with `h-screen overflow-hidden` and inner `overflow-y-auto` panels.
2. **Keyboard Accessibility**: Bind `k` with `metaKey`/`ctrlKey` for search focus. Bind `Enter` for Copilot submit.
3. **No Mobile Assumptions**: The target is an enterprise desktop workstation. Ensure dense, high-efficiency information density with readable typography.

---

## 7. Atelier Monolith Design System Tokens

```yaml
name: Atelier Monolith
colors:
  surface: '#fbf8ff'
  surface-dim: '#dad9e3'
  surface-bright: '#fbf8ff'
  surface-container-lowest: '#ffffff'
  surface-container-low: '#f4f2fd'
  surface-container: '#eeedf7'
  surface-container-high: '#e8e7f1'
  surface-container-highest: '#e3e1ec'
  on-surface: '#1a1b22'
  on-surface-variant: '#45464c'
  inverse-surface: '#2f3038'
  inverse-on-surface: '#f1effa'
  outline: '#76777d'
  outline-variant: '#c6c6cd'
  surface-tint: '#575e70'
  primary: '#000000'
  on-primary: '#ffffff'
  primary-container: '#141b2b'
  on-primary-container: '#7d8497'
  inverse-primary: '#c0c6db'
  secondary: '#715b38'
  on-secondary: '#ffffff'
  secondary-container: '#fddeb2'
  on-secondary-container: '#78613e'
  tertiary: '#000000'
  on-tertiary: '#ffffff'
  tertiary-container: '#2a1700'
  on-tertiary-container: '#b87500'
  error: '#ba1a1a'
  on-error: '#ffffff'
  error-container: '#ffdad6'
  on-error-container: '#93000a'
  background: '#fbf8ff'
  on-background: '#1a1b22'
  surface-variant: '#e3e1ec'
typography:
  display: { fontFamily: Newsreader, fontSize: 48px }
  headline-md: { fontFamily: Newsreader, fontSize: 26px }
  headline-sm: { fontFamily: Newsreader, fontSize: 20px }
  body-md: { fontFamily: Geist, fontSize: 15px }
  body-sm: { fontFamily: Geist, fontSize: 13px }
  label-sm: { fontFamily: Geist, fontSize: 11px }
  code: { fontFamily: JetBrains Mono, fontSize: 13px }
```
