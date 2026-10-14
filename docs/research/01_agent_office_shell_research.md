# 픽셀 사무실 "껍데기" 조사 보고서

> 작성일: 2026-10-14
> 목적: 관리 기능(채용, 배정, 진행 확인, 루프)은 직접 만들고, 픽셀 사무실 화면만 가져오기 위한 후보 조사.
> 원칙: **라이선스가 자유로운 것 중심.**

---

## 1. 결론 요약

| 항목 | 결론 |
|---|---|
| **껍데기로 쓸 것** | **Pixel Agents** (MIT). 코드도 그림도 자유롭게 쓸 수 있어요. |
| **참고만 할 것** | **Agent Office** (alminisl). 기능 아이디어는 최고 수준이지만 라이선스가 정해지지 않았어요(`License: TBD`). 그래서 **코드를 가져다 쓰면 안 돼요.** 기능 아이디어만 참고하고 직접 구현해야 해요. |
| **그림 저작권** | Pixel Agents 캐릭터의 원본 팩은 **CC0**(누구나 무료, 상업적 이용 가능)이에요. 추가 그림이 필요하면 CC0 에셋을 쓰거나 코드로 그림을 그리는 방식(절차적 생성)으로 해결할 수 있어요. |

---

## 2. Pixel Agents (껍데기 후보 1순위)

- 저장소: https://github.com/pixel-agents-hq/pixel-agents
- 라이선스: **MIT** (코드)
- 규모: TypeScript 약 4.6만 줄. 꾸준히 관리되고 있어요 (v1.4.1).

### 2.1 구조: 화면과 엔진이 깔끔하게 나뉘어 있어요
```
core/            통신 규칙(asyncapi.yaml)과 공용 타입 ← 화면과 서버가 주고받는 메시지 정의
server/          런타임: Claude Code 기록 읽기, 에이전트 상태 관리, WebSocket 서버(Fastify)
adapters/vscode  VS Code용 연결부
webview-ui/      화면: React와 캔버스로 그린 픽셀 사무실
  src/office/    사무실 엔진 (캐릭터, 가구, 바닥, 벽, 레이아웃 편집기)
  src/transport/ 통신부 (postMessage / WebSocket 두 가지)
```
- **화면은 정해진 메시지만 받으면 움직여요.** `agentCreated`, `agentToolStart`, `agentToolDone`, `agentStatus`, `subagentToolStart` 같은 메시지예요. `core/asyncapi.yaml`에 약 60종이 정의돼 있어요.
- 그래서 **우리 백엔드가 같은 메시지를 보내기만 하면** 사무실 화면을 그대로 쓸 수 있어요. 화면 코드는 거의 안 고쳐도 돼요.
- 독립 실행판(`npx pixel-agents`)은 이미 **브라우저 + WebSocket** 구조예요. 다른 기기에서 접속하는 것도 설계에 들어 있어요("can be reached from another device").

### 2.2 이미 있는 것 / 없는 것
| 이미 있음 | 없음 (우리가 만들 것) |
|---|---|
| 캐릭터 애니메이션 (걷기, 타이핑, 읽기) | 할 일 보드와 드래그 배정 |
| 서브에이전트와 팀원 시각화 | 직원 채용, 수정, 삭제 화면 |
| 승인 대기와 완료 말풍선 | 결과 검토와 점수 |
| 사무실 편집기, 구역(Areas), 펫 | 루프 엔진 (검수 → 재작업 → 회고) |
| 외부 에셋 폴더 불러오기 | Slack 등 외부 채널 |
| 새 에이전트 띄우기 (`launchAgent`) | 예산과 사용량 한도 |

### 2.3 그림 에셋 라이선스
| 에셋 | 출처 | 라이선스 |
|---|---|---|
| 캐릭터 6종 | JIK-A-4 "MetroCity Free Top Down Character Pack" 기반 | **CC0** (상업적 이용 가능, 출처 표시 불필요) |
| 가구, 바닥, 벽, 카펫 | v1.0 시절 "독점 타일셋을 오픈소스 에셋으로 교체"(#117) | 오픈소스로 교체됨. **개별 출처는 공개 전에 재확인 필요** |

---

## 3. Agent Office (기능 참고용)

- 저장소: https://github.com/alminisl/agent-office
- 라이선스: **TBD (미정)** → 법적으로는 "모든 권리 보유" 상태라 **코드 재사용 불가**예요. 쓰고 싶으면 작성자에게 라이선스를 문의해야 해요.
- 특징: Node 서버 하나와 캔버스 화면. **그림 파일이 하나도 없고 모든 캐릭터와 가구를 코드로 그려요.** 이 방식이면 저작권 문제가 원천적으로 없어요.

### 3.1 훔쳐 올 만한 기능 아이디어 (직접 구현)
| 기능 | 내용 | 우리 6대 목표 |
|---|---|---|
| 오피스 보드 | 할 일 / 진행 중 / 완료. 카드를 드래그하고 **🤝 직원에게 주기**, **🏢 이 일로 채용하기** | 3, 4 |
| 역할 채용 | Fixer, PR 리뷰어, QA, 보안 감사 등 역할 단위 채용 | 4 |
| 백그라운드 근무 | `claude -p`로 사무실 안에서 일하고 📋 보고서를 제출 | 1, 2 |
| PM 에이전트 | 모든 직원 상황을 브리핑받고 "뭐가 막혔어?"에 답함 | 2 |
| 상태 줄 | "⌨️ 작업 중: Cart.tsx 수정", "🙋 승인 필요" | 1, 2 |
| 컨텍스트 바 | 대화 용량 80% 넘으면 캐릭터가 땀을 흘림 | 2 |
| 성격 → 작업 방식 | 성격 설정이 실제 지시문(`--append-system-prompt`)에 반영됨 | 5 |
| XP, 레벨, 승진 | 레벨 5가 되면 임원실로 이동 | 재미 |
| 다중 리뷰 | 여러 리뷰어가 독립적으로 검토하고 결과를 종합 | 6 |

---

## 4. 그림 저작권 대안 (CC0 / 자체 생성)

| 방법 | 내용 | 비고 |
|---|---|---|
| **CC0 에셋** | MetroCity 캐릭터(CC0), 2dPig "Pixel Office"(CC0, 캐릭터 5명과 사무용품), OpenGameArt의 CC0 캐릭터 시트 | 가장 빠름 |
| **절차적 생성** | 피부, 머리, 옷, 안경 같은 부품을 코드로 무작위 조합해 캐릭터 생성 (Agent Office 방식을 직접 구현) | 저작권 걱정 없음, 직원마다 고유 외형 |
| **AI 생성 (Hugging Face)** | 픽셀아트 생성 모델로 스프라이트 생성 | 모델마다 라이선스와 생성물 권리가 달라서 **모델별 확인 필요**. 애니메이션 프레임 일관성은 아직 약함 |

**추천**: 처음엔 **Pixel Agents 기본 캐릭터(CC0) + 절차적 색상 변형**으로 시작하고, 나중에 "직원 고유 외형"이 필요해지면 부품 조합 생성기를 추가해요.

---

## 5. 제안하는 다음 단계

1. **Pixel Agents를 복제해서 새 저장소 `subrain-hq` 만들기** (MIT 표기 유지)
2. **우리 백엔드가 Pixel Agents 메시지 규칙(asyncapi)을 그대로 보내도록 설계** → 화면은 그대로, 관리 기능은 옆 패널로 추가
3. **화면과 사용자 흐름 설계**: 보드(드래그 배정), 채용 모달, 직원 상세(지시문 수정), 결과와 루프 화면
4. 단계별 구현: 보기 → 채용과 수정 → 배정 → 루프

---

## 6. 멀티 엔진 (Claude Code · Codex · Gemini) 연동

- Pixel Agents는 이미 **엔진별 어댑터(Provider) 구조**예요. `core/src/provider.ts`가 엔진과 상관없는 공통 이벤트(`toolStart`, `toolEnd`, `turnEnd`, `subagentStart`, `permissionRequest` 등)를 정의하고, 지금은 `server/src/providers/hook/claude`만 구현돼 있어요. README 로드맵에도 Codex와 Gemini가 올라 있어요.
- 우리 백엔드도 같은 원칙으로 설계해요: **엔진마다 어댑터 하나, 위로는 공통 이벤트만.**

| 엔진 | 실행 방법 (비대화형) | 직원 지시문 위치 | 사용량 |
|---|---|---|---|
| Claude Code | `claude -p` / Claude Agent SDK | `.claude/agents/*.md`, `CLAUDE.md` | Claude 플랜 |
| Codex | `codex exec` / Codex SDK | `AGENTS.md` | ChatGPT 플랜 또는 OpenAI API |
| Gemini | `gemini -p` (Gemini CLI) | `GEMINI.md` | Google 계정 또는 Gemini API |

- **Antigravity 주의**: Antigravity는 IDE라서 외부 앱이 일을 시킬 수 있는 공식 실행 통로가 없어요. Gemini 연동은 **Gemini CLI** 기준으로 하고, Antigravity 한도와 Gemini CLI 한도가 같은지는 확인이 필요해요.
- **직원 정의는 우리 형식 하나로 저장**하고, 일을 시킬 때 엔진에 맞는 형식으로 변환해요. 같은 직원을 Claude, Codex, Gemini 어느 엔진으로든 돌릴 수 있게 돼요.
- 이점: 한 엔진의 한도가 다 차면 다른 엔진으로 넘기기(폴백), 단계별로 엔진 섞기(예: 초안은 Gemini, 검수는 Claude).

## 출처
- Pixel Agents: https://github.com/pixel-agents-hq/pixel-agents (LICENSE, README, CONTEXT.md, core/asyncapi.yaml, CHANGELOG #117)
- Agent Office: https://github.com/alminisl/agent-office (README "License: TBD")
- MetroCity 캐릭터 팩 (CC0): https://jik-a-4.itch.io/metrocity-free-topdown-character-pack
- 2dPig Pixel Office (CC0): https://2dpig.itch.io/pixel-office
- OpenGameArt CC0 캐릭터 예: https://opengameart.org/content/top-down-player-sprite-sheet-julia
