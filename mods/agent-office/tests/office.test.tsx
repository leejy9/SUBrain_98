import { expect, mock, test } from 'claude-code/testing'

const SCROLL = { offset: 0, bodyRows: 40, contentRows: 0 }
const VIEW = {}
const PANE = {
  plugin: 'agent-office',
  component: 'Pane',
  requestId: 'agent-office',
  props: { title: '사무실', isFocused: false, bodyColumns: 100, placement: 'dock', scroll: SCROLL, view: VIEW } as never,
} as const
const BAND = {
  plugin: 'agent-office',
  component: 'AbovePrompt',
  props: { hasSurvey: false, isWorking: true, maxRows: 10, bodyColumns: 100, scroll: SCROLL, view: VIEW } as never,
} as const

test('직원이 출근하고, 일하고, 보고하면 사무실과 휴게실에 보인다', async ($, on) => {
  mock.clock(on, { now: 1_000_000 })
  mock.store(on)
  const toasts: string[] = []
  on('ui.toast', ($, e) => {
    toasts.push(e.text)
    return { value: undefined }
  })
  on('agent.spawn', () => ({ model: 'test-model', agentId: 'a1' }))
  on('tool.call', () => ({ result: 'ok' }))
  on('turn.complete', () => ({ text: '' }))

  await $.agent.spawn({
    tool_use_id: 't1',
    prompt: '로그인 버그 원인 찾기',
    description: '로그인 버그 조사',
    subagentType: 'Explore',
    background: false,
    fork: false,
    parentModel: 'test-model',
    provider: { plugin: 'engine', tier: 'core' },
  } as never)
  await $.tool.call({ tool: 'Grep', tool_use_id: 't2', pattern: 'login', agentId: 'a1' } as never)

  for (const surface of ['terminal', 'desktop'] as const) {
    const ui = await $.ui.mount({ ...PANE, surface })
    expect(await ui.find({ type: 'Text', text: /조사팀/ })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /서류 검토 중/ })).toBeDefined()
    await ui.unmount()

    const band = await $.ui.mount({ ...BAND, surface })
    expect(await band.find({ key: 'open' })).toBeDefined()
    await band.unmount()
  }

  await $.turn.complete({
    answer: '원인은 세션 만료 처리',
    durationMs: 1000,
    isAborted: false,
    turnId: 'r1',
    agentId: 'a1',
    reason: 'answer',
  } as never)

  for (const surface of ['terminal', 'desktop'] as const) {
    const ui = await $.ui.mount({ ...PANE, surface })
    expect(await ui.find({ type: 'Text', text: /보고 완료/ })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /완료 업무 1건/ })).toBeDefined()
    await ui.unmount()
  }
  expect(toasts.some(t => t.includes('조사팀 출근'))).toBe(true)
  expect(toasts.some(t => t.includes('Lv.2 승진'))).toBe(true)
})

test('팀장(메인 에이전트)의 도구 사용이 팀장실에 보인다', async ($, on) => {
  mock.clock(on, { now: 1_000_000 })
  mock.store(on)
  on('tool.call', () => ({ result: 'ok' }))

  await $.tool.call({ tool: 'Edit', tool_use_id: 't9', file_path: 'a.md', old_string: 'a', new_string: 'b' } as never)

  const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
  expect(await ui.find({ type: 'Text', text: /타자 치는 중/ })).toBeDefined()
})
