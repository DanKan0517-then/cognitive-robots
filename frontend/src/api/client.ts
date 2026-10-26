import type {
  AgentDetail, AgentRole, AgentStatus, DashboardSummary, DecisionRecord,
  Message, Mission, MissionReport, PendingApproval, ScenarioDefinition, Task, TaskStatus,
  WorldSnapshot,
} from '../types';

const BASE = '/api';

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail ?? detail;
    } catch {
      /* no body */
    }
    throw new Error(`${res.status} ${detail}`);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

export const api = {
  // agents
  listAgents: () => request<AgentStatus[]>('/agents'),
  createAgent: (body: { name: string; role: AgentRole; capabilities: string[]; objective?: string }) =>
    request<AgentStatus>('/agents', { method: 'POST', body: JSON.stringify(body) }),
  getAgent: (id: string) => request<AgentDetail>(`/agents/${id}`),
  updateAgent: (id: string, body: { objective?: string; capabilities?: string[]; enabled?: boolean }) =>
    request<AgentStatus>(`/agents/${id}`, { method: 'PATCH', body: JSON.stringify(body) }),
  removeAgent: (id: string) => request<{ removed: string }>(`/agents/${id}`, { method: 'DELETE' }),
  agentEvents: (id: string, limit = 100) =>
    request<{ decisions: DecisionRecord[]; messages: Message[] }>(`/agents/${id}/events?limit=${limit}`),

  // missions
  listMissions: () => request<Mission[]>('/missions'),
  createMission: (body: { name: string; goal: string; scenario_key: string; priority?: number }) =>
    request<Mission>('/missions', { method: 'POST', body: JSON.stringify(body) }),
  getMission: (id: string) => request<MissionReport>(`/missions/${id}`),
  cancelMission: (id: string) => request<Mission>(`/missions/${id}/cancel`, { method: 'POST' }),
  retryMission: (id: string) => request<{ mission_id: string; tasks_reset: number }>(`/missions/${id}/retry`, { method: 'POST' }),
  exportMission: (id: string) => request<MissionReport & { messages: Message[]; decisions: DecisionRecord[] }>(`/missions/${id}/export`),

  // tasks
  listTasks: (params?: { mission_id?: string; status?: TaskStatus }) => {
    const q = new URLSearchParams();
    if (params?.mission_id) q.set('mission_id', params.mission_id);
    if (params?.status) q.set('status', params.status);
    const qs = q.toString();
    return request<Task[]>(`/tasks${qs ? `?${qs}` : ''}`);
  },
  getTask: (id: string) => request<Task>(`/tasks/${id}`),

  // approvals
  listApprovals: () => request<PendingApproval[]>('/approvals'),
  decideApproval: (taskId: string, approve: boolean) =>
    request<{ task_id: string; approved: boolean }>(`/approvals/${taskId}`, {
      method: 'POST',
      body: JSON.stringify({ approve }),
    }),

  // world
  getWorld: () => request<WorldSnapshot>('/world'),
  postWorldEvent: (body: { kind: string; description: string; entity_id?: string; payload?: Record<string, unknown> }) =>
    request('/world/events', { method: 'POST', body: JSON.stringify(body) }),

  // comms
  listMessages: (params?: { agent_id?: string; mission_id?: string; message_type?: string; limit?: number }) => {
    const q = new URLSearchParams();
    if (params?.agent_id) q.set('agent_id', params.agent_id);
    if (params?.mission_id) q.set('mission_id', params.mission_id);
    if (params?.message_type) q.set('message_type', params.message_type);
    if (params?.limit) q.set('limit', String(params.limit));
    const qs = q.toString();
    return request<Message[]>(`/messages${qs ? `?${qs}` : ''}`);
  },
  listDecisions: (params?: { agent_id?: string; mission_id?: string; limit?: number }) => {
    const q = new URLSearchParams();
    if (params?.agent_id) q.set('agent_id', params.agent_id);
    if (params?.mission_id) q.set('mission_id', params.mission_id);
    if (params?.limit) q.set('limit', String(params.limit));
    const qs = q.toString();
    return request<DecisionRecord[]>(`/decisions${qs ? `?${qs}` : ''}`);
  },

  // simulation
  startSimulation: (key: string) => request<{ mission: Mission; [k: string]: unknown }>('/simulation/start', {
    method: 'POST',
    body: JSON.stringify({ key }),
  }),
  pauseSimulation: () => request<{ paused: boolean }>('/simulation/pause', { method: 'POST' }),
  resumeSimulation: () => request<{ paused: boolean }>('/simulation/resume', { method: 'POST' }),
  stepSimulation: () => request<{ sim_time: number }>('/simulation/step', { method: 'POST' }),
  setSpeed: (speed: number) => request<{ speed: number }>('/simulation/speed', {
    method: 'POST',
    body: JSON.stringify({ speed }),
  }),
  resetSimulation: () => request<{ reset: boolean }>('/simulation/reset', { method: 'POST' }),
  getSummary: () => request<DashboardSummary>('/simulation/summary'),

  // scenarios
  listScenarios: () => request<ScenarioDefinition[]>('/scenarios'),
  createScenario: (body: ScenarioDefinition) => request('/scenarios', { method: 'POST', body: JSON.stringify(body) }),
};
