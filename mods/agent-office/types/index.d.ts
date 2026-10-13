export type EmployeeStatus = 'working' | 'done' | 'failed'

export type Employee = {
  id: string
  type: string
  task: string
  status: EmployeeStatus
  action: string
  tools: number
  startedAt: number
  endedAt?: number
}

export type Boss = {
  isWorking: boolean
  action: string
  tools: number
}

export type RosterEntry = { jobs: number; firstHiredAt: number }

export type Roster = Record<string, RosterEntry>

declare module 'claude-code' {
  interface PluginState {
    'agent-office': {
      staff: Employee[]
      boss: Boss
      frame: number
      roster: Roster
    }
  }
}
