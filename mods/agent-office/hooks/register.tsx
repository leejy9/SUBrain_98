import { atom, read, update } from 'claude-code'
import type { Register } from 'claude-code'

import type { Boss, Employee, Roster } from '../types'

const PANE = 'agent-office'
const ROSTER_KEY = 'roster'

const staff = atom({ plugin: 'agent-office', key: 'staff' } as const, [] as Employee[])
const boss = atom({ plugin: 'agent-office', key: 'boss' } as const, {
  isWorking: false,
  action: '☕ 결재 대기 중',
  tools: 0,
} as Boss)
const frame = atom({ plugin: 'agent-office', key: 'frame' } as const, 0)
const roster = atom({ plugin: 'agent-office', key: 'roster' } as const, {} as Roster)

// 서브에이전트 종류 → 부서와 캐릭터
const DEPARTMENTS: Record<string, { face: string; team: string }> = {
  'general-purpose': { face: '🧑‍💼', team: '만능사원' },
  Explore: { face: '🕵️', team: '조사팀' },
  Plan: { face: '🧑‍🔬', team: '기획팀' },
  'claude-code-guide': { face: '📚', team: '사내 가이드' },
  'statusline-setup': { face: '🎨', team: '디자인팀' },
  fork: { face: '👯', team: '분신' },
}

function departmentOf(type: string) {
  return DEPARTMENTS[type] ?? { face: '👷', team: type }
}

// 도구 이름 → 사무실에서 하는 행동
function actionOf(tool: string): string {
  if (tool === 'Read' || tool === 'Glob' || tool === 'Grep') return '📖 서류 검토 중'
  if (tool === 'Edit' || tool === 'Write' || tool === 'NotebookEdit') return '⌨️ 타자 치는 중'
  if (tool === 'Bash' || tool === 'Monitor') return '🔧 기계 돌리는 중'
  if (tool === 'WebSearch' || tool === 'WebFetch') return '🌐 자료 조사 중'
  if (tool === 'Agent' || tool === 'Workflow') return '📣 업무 지시 중'
  if (tool === 'SendMessage') return '💬 메신저 보내는 중'
  if (tool.startsWith('Task') || tool === 'TodoWrite') return '📋 업무 정리 중'
  if (tool === 'Skill') return '📘 매뉴얼 펼치는 중'
  if (tool.startsWith('mcp__')) return `📞 외부 연락 중 (${tool.split('__')[1] ?? tool})`
  return `💼 ${tool} 작업 중`
}

// 완료한 업무 수 → 레벨 (1, 4, 9, 16 … 건마다 승진)
function levelOf(jobs: number) {
  return Math.floor(Math.sqrt(jobs)) + 1
}

function elapsed(from: number, to: number) {
  const s = Math.max(0, Math.round((to - from) / 1000))
  return s < 60 ? `${s}초` : `${Math.floor(s / 60)}분 ${s % 60}초`
}

const TYPING = ['▖', '▘', '▝', '▗']

function officeText(list: Employee[], b: Boss, ranks: Roster, now: number) {
  const working = list.filter(one => one.status === 'working')
  const resting = list.filter(one => one.status !== 'working')
  const lines = [
    `🏢 우리 회사 · 오늘 출근 ${list.length}명 (근무 중 ${working.length})`,
    '',
    `👑 팀장실 — Claude: ${b.action} · 도구 ${b.tools}회`,
    '',
    '🪑 사무실',
  ]
  if (working.length === 0) lines.push('  지금 일하는 직원이 없어요.')
  for (const one of working) {
    const { face, team } = departmentOf(one.type)
    lines.push(
      `  ${face} ${team} Lv.${levelOf(ranks[one.type]?.jobs ?? 0)} · “${one.task}” · ${one.action} · ⏱ ${elapsed(one.startedAt, now)} · 🔨 ${one.tools}회`,
    )
  }
  lines.push('', '☕ 휴게실')
  if (resting.length === 0) lines.push('  아직 퇴근한 직원이 없어요.')
  for (const one of resting.slice(-8).reverse()) {
    const { face, team } = departmentOf(one.type)
    lines.push(`  ${face} ${team} ${one.action} · “${one.task}” · ${elapsed(one.startedAt, one.endedAt ?? now)}`)
  }
  lines.push('', '📒 인사기록부')
  const veterans = Object.entries(ranks).sort((a, z) => z[1].jobs - a[1].jobs)
  if (veterans.length === 0) lines.push('  아직 기록이 없어요.')
  for (const [type, rec] of veterans) {
    const { face, team } = departmentOf(type)
    lines.push(`  ${face} ${team} Lv.${levelOf(rec.jobs)} · 완료 업무 ${rec.jobs}건`)
  }

  return lines.join('\n')
}

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    await $.command.register({
      name: 'office',
      description: '팀장(메인 에이전트)과 직원(서브에이전트)이 일하는 사무실을 엽니다',
    })

    // 지난 세션들의 직원 경력은 $.store에 남아 있어요
    const saved = (await $.store.get(ROSTER_KEY)) as Roster | undefined
    if (saved) await update($, roster, () => saved)

    // 누군가 일하는 동안만 애니메이션 프레임을 넘겨요
    $.clock.every(700, () => {
      void (async () => {
        const list = await read($, staff)
        const b = await read($, boss)
        if (b.isWorking || list.some(one => one.status === 'working')) {
          await update($, frame, n => (n + 1) % 1000)
        }
      })()
    })

    return next(e)
  })

  // 패널을 그리지 않는 화면(일부 앱)에서도 보이도록 사무실 현황을 글로도 돌려줘요
  on('command.run', { command: 'office' }, async $ => {
    const opened = await $.ui.open({ id: PANE, title: '🏢 우리 회사 사무실' })
    const snapshot = officeText(await read($, staff), await read($, boss), await read($, roster), await $.clock.now())
    const note = opened.isPlaced ? '' : `\n\n(이 화면에는 사무실 패널을 띄울 수 없어 글로 보여드려요: ${opened.reason})`

    return { text: snapshot + note }
  })

  on('prompt.submit', async ($, e, next) => {
    await update($, boss, b => ({ ...b, isWorking: true, action: '🧠 업무 파악 중' }))

    return next(e)
  })

  // 직원 채용(서브에이전트 시작)
  on('agent.spawn', async ($, e, next) => {
    const started = await next(e)
    if (started.deny !== undefined || started.agentId === undefined) return started

    const now = await $.clock.now()
    const hire: Employee = {
      id: started.agentId,
      type: e.subagentType,
      task: e.description,
      status: 'working',
      action: '🚶 출근하는 중',
      tools: 0,
      startedAt: now,
    }
    await update($, staff, list => [...list, hire].slice(-30))

    const { face, team } = departmentOf(e.subagentType)
    $.ui.toast(`${face} ${team} 출근: ${e.description}`)

    return started
  })

  // 누가 어떤 도구를 쓰는지 → 행동으로 바꿔 보여줘요
  on('tool.call', async ($, e, next) => {
    const tool = String(e.tool)
    const action = actionOf(tool)

    if (e.agentId === undefined) {
      await update($, boss, b => ({ ...b, isWorking: true, action, tools: b.tools + 1 }))
    } else {
      const id = e.agentId
      await update($, staff, list =>
        list.map(one => (one.id === id ? { ...one, action, tools: one.tools + 1 } : one)),
      )
    }

    return next(e)
  })

  // 업무 보고(턴 종료)
  on('turn.complete', async ($, e, next) => {
    if (e.agentId === undefined) {
      await update($, boss, b => ({ ...b, isWorking: false, action: '☕ 결재 대기 중' }))

      return next(e)
    }

    const id = e.agentId
    const list = await read($, staff)
    const one = list.find(x => x.id === id)
    if (one === undefined || one.status !== 'working') return next(e)

    const failed = e.isAborted || e.reason === 'error'
    const now = await $.clock.now()
    await update($, staff, all =>
      all.map(x =>
        x.id === id
          ? {
              ...x,
              status: failed ? 'failed' : 'done',
              action: failed ? '😵 조퇴' : '✅ 보고 완료',
              endedAt: now,
            }
          : x,
      ),
    )

    if (!failed) {
      const before = (await read($, roster))[one.type]
      const jobs = (before?.jobs ?? 0) + 1
      const next_: Roster = {
        ...(await read($, roster)),
        [one.type]: { jobs, firstHiredAt: before?.firstHiredAt ?? one.startedAt },
      }
      await update($, roster, () => next_)
      await $.store.set(ROSTER_KEY, next_)

      const { face, team } = departmentOf(one.type)
      if (levelOf(jobs) > levelOf(jobs - 1)) {
        $.ui.toast(`🎉 ${face} ${team} Lv.${levelOf(jobs)} 승진!`)
      }
    }

    return next(e)
  })

  on('session.end', async ($, e, next) => {
    await update($, staff, () => [])

    return next(e)
  })

  // 입력창 위의 한 줄 사무실 띠
  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    if (e.props.hasSurvey) return next(e)

    const list = await read($, staff)
    const b = await read($, boss)
    const tick = await read($, frame)
    const working = list.filter(one => one.status === 'working')
    const resting = list.length - working.length

    if (!b.isWorking && working.length === 0) return next(e)

    const { Box, Text, Button } = $.ui.resolve(e)
    const cursor = TYPING[tick % TYPING.length]

    return (
      <Box flexDirection="row" gap={1}>
        <Text bold>🏢</Text>
        <Text color="yellow">👑 {b.action}</Text>
        {working.map(one => (
          <Text key={one.id}>
            │ {departmentOf(one.type).face} {one.action.split(' ')[0]}
            {cursor}
          </Text>
        ))}
        {resting > 0 && <Text dimColor>│ ☕×{resting}</Text>}
        <Button key="open" plain label="사무실 보기" onPress={() => $.ui.open({ id: PANE, title: '🏢 우리 회사 사무실' })} />
      </Box>
    )
  })

  // 사무실 전체 화면 (/office)
  on('ui.render', { component: 'Pane', requestId: PANE }, async ($, e) => {
    const { Box, Text } = $.ui.resolve(e)
    const list = await read($, staff)
    const b = await read($, boss)
    const tick = await read($, frame)
    const ranks = await read($, roster)
    const now = await $.clock.now()

    const working = list.filter(one => one.status === 'working')
    const resting = list.filter(one => one.status !== 'working')
    const cursor = TYPING[tick % TYPING.length]
    const deskWidth = 30
    const veterans = Object.entries(ranks).sort((a, z) => z[1].jobs - a[1].jobs)

    return (
      <Box flexDirection="column" gap={1}>
        <Text bold>
          🏢 우리 회사 · 오늘 출근 {list.length}명 (근무 중 {working.length})
        </Text>

        <Box borderStyle="double" borderColor="yellow" flexDirection="column" paddingX={1}>
          <Text bold color="yellow">👑 팀장실 — Claude</Text>
          <Text>
            {b.action}
            {b.isWorking ? ` ${cursor}` : ''}
          </Text>
          <Text dimColor>오늘 도구 사용 {b.tools}회</Text>
        </Box>

        <Text bold>🪑 사무실</Text>
        {working.length === 0 && <Text dimColor>  지금 일하는 직원이 없어요. 서브에이전트를 부르면 여기 앉아요.</Text>}
        <Box flexDirection="row" flexWrap="wrap" gap={1}>
          {working.map(one => {
            const { face, team } = departmentOf(one.type)
            const lv = levelOf(ranks[one.type]?.jobs ?? 0)

            return (
              <Box
                key={one.id}
                borderStyle="round"
                borderColor="cyan"
                flexDirection="column"
                paddingX={1}
                width={deskWidth}
              >
                <Text bold>
                  {face} {team} <Text color="green">Lv.{lv}</Text>
                </Text>
                <Text wrap="truncate-end" dimColor>“{one.task}”</Text>
                <Text>
                  {one.action} {cursor}
                </Text>
                <Text dimColor>
                  ⏱ {elapsed(one.startedAt, now)} · 🔨 {one.tools}회
                </Text>
              </Box>
            )
          })}
        </Box>

        <Text bold>☕ 휴게실</Text>
        {resting.length === 0 ? (
          <Text dimColor>  아직 퇴근한 직원이 없어요.</Text>
        ) : (
          resting
            .slice(-8)
            .reverse()
            .map(one => {
              const { face, team } = departmentOf(one.type)

              return (
                <Text key={one.id} dimColor={one.status === 'done'} color={one.status === 'failed' ? 'red' : undefined}>
                  {'  '}
                  {face} {team} {one.action} · “{one.task}” · {elapsed(one.startedAt, one.endedAt ?? now)} · 🔨{one.tools}
                </Text>
              )
            })
        )}

        <Text bold>📒 인사기록부 (모든 세션 누적)</Text>
        {veterans.length === 0 ? (
          <Text dimColor>  아직 기록이 없어요.</Text>
        ) : (
          veterans.map(([type, rec]) => {
            const { face, team } = departmentOf(type)

            return (
              <Text key={type}>
                {'  '}
                {face} {team} <Text color="green">Lv.{levelOf(rec.jobs)}</Text>
                <Text dimColor> · 완료 업무 {rec.jobs}건</Text>
              </Text>
            )
          })
        )}
      </Box>
    )
  })
}
