# 🏢 agent-office — 우리 회사 사무실 Mod

Claude Code의 메인 에이전트를 **팀장**, 서브에이전트를 **직원**으로 보여주는 Mod입니다.

- **입력창 위 한 줄 띠**: 누가 지금 무슨 일을 하는지 (`👑 ⌨️ 타자 치는 중 │ 🕵️ 📖▖ │ ☕×2`)
- **`/office` 사무실 화면**: 팀장실 · 직원 책상 · 휴게실 · 인사기록부
- **출근/승진 알림**: 서브에이전트가 시작되면 "출근", 업무 완료가 쌓이면 레벨업 (1·4·9·16…건)
- 인사기록부(레벨)는 `$.store`에 저장되어 **세션과 프로젝트를 넘어 누적**됩니다.

| 도구 | 사무실 행동 |
|---|---|
| Read / Grep / Glob | 📖 서류 검토 중 |
| Edit / Write | ⌨️ 타자 치는 중 |
| Bash | 🔧 기계 돌리는 중 |
| WebSearch / WebFetch | 🌐 자료 조사 중 |
| Agent | 📣 업무 지시 중 |
| MCP 도구 | 📞 외부 연락 중 |

## 설치 (로컬 터미널의 Claude Code에서)

```
/plugin install agent-office --marketplace leejy9/SUBrain_98
```

`y`로 마켓플레이스를 추가하고, 범위는 **user**를 고르면 모든 프로젝트에서 켜집니다.

## 개발

```
claude plugin validate mods/agent-office
claude plugin test mods/agent-office
```
