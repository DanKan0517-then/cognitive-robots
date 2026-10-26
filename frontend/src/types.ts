// Mirrors backend/app/core/schemas.py exactly. Keep in sync — these are not
// invented shapes, they are the real wire format the API and WebSocket send.

export type AgentRole =
  | 'perception' | 'world_model' | 'planning' | 'reasoning' | 'critic'
  | 'coordinator' | 'executor' | 'memory' | 'custom';

export type AgentState =
  | 'idle' | 'observing' | 'reasoning' | 'planning' | 'negotiating'
  | 'executing' | 'verifying' | 'completed' | 'waiting_for_agent'
  | 'blocked' | 'failed' | 'recovering' | 'stopped';

export interface AgentStatus {
  agent_id: string;
  name: string;
  role: AgentRole;
  state: AgentState;
  objective: string;
  current_task_id: string | null;
  last_updated: string;
  health: 'healthy' | 'degraded' | 'unresponsive';
  error: string | null;
  messages_sent: number;
  messages_received: number;
  decisions_made: number;
}

export interface AgentConfig {
  agent_id: string;
  name: string;
  role: AgentRole;
  capabilities: string[];
  objective: string;
  enabled: boolean;
  max_retries: number;
  timeout_seconds: number;
}

export interface AgentDetail {
  status: AgentStatus;
  config: AgentConfig;
  recent_observations: string[];
  recent_decisions: DecisionRecord[];
  recent_messages: Message[];
  blockers: string[];
}

export type MessageType =
  | 'observation' | 'state_update' | 'proposal' | 'counterproposal'
  | 'critique' | 'rejection' | 'approval' | 'task_assignment'
  | 'task_completion' | 'info_request' | 'info_response' | 'event_notice'
  | 'ack' | 'alert' | 'execution_result' | 'verification_result'
  | 'replan_request' | 'broadcast';

export type MessagePriority = 'low' | 'normal' | 'high' | 'critical';
export type MessageStatus = 'pending' | 'delivered' | 'acknowledged' | 'rejected' | 'timed_out' | 'failed';

export interface Message {
  message_id: string;
  correlation_id: string;
  sender_id: string;
  receiver_id: string | null;
  message_type: MessageType;
  timestamp: string;
  priority: MessagePriority;
  payload: Record<string, unknown>;
  status: MessageStatus;
  requires_ack: boolean;
  ttl_seconds: number;
  mission_id: string | null;
  task_id: string | null;
}

export interface DecisionRecord {
  decision_id: string;
  agent_id: string;
  mission_id: string | null;
  task_id: string | null;
  objective: string;
  observations: string[];
  memory_refs: string[];
  candidate_actions: string[];
  selected_action: string | null;
  rationale: string;
  confidence: number;
  constraints: string[];
  risks: string[];
  requires_approval: boolean;
  approved_by: string | null;
  execution_result: Record<string, unknown> | null;
  verification_result: Record<string, unknown> | null;
  timestamp: string;
}

export type TaskStatus = 'pending' | 'assigned' | 'in_progress' | 'blocked' | 'completed' | 'failed' | 'cancelled';

export interface Task {
  task_id: string;
  mission_id: string;
  title: string;
  description: string;
  priority: number;
  status: TaskStatus;
  assigned_agent_id: string | null;
  target_entity_id: string | null;
  depends_on: string[];
  created_at: string;
  updated_at: string;
  retries: number;
  max_retries: number;
  result: Record<string, unknown> | null;
  error: string | null;
}

export type MissionStatus = 'draft' | 'active' | 'paused' | 'completed' | 'failed' | 'cancelled';

export interface Mission {
  mission_id: string;
  name: string;
  goal: string;
  scenario_key: string;
  status: MissionStatus;
  priority: number;
  created_at: string;
  updated_at: string;
  task_ids: string[];
  deadline: string | null;
  outcome: string | null;
}

export interface MissionReport {
  mission: Mission;
  tasks: Task[];
  progress: { completed: number; total: number };
  messages?: Message[];
  decisions?: DecisionRecord[];
}

export interface WorldEntity {
  entity_id: string;
  kind: string;
  label: string;
  x: number;
  y: number;
  zone_id: string | null;
  attributes: Record<string, unknown>;
  last_updated: string;
}

export interface WorldEvent {
  event_id: string;
  kind: string;
  description: string;
  payload: Record<string, unknown>;
  timestamp: string;
  source: string;
}

export interface WorldSnapshot {
  width: number;
  height: number;
  sim_time: number;
  entities: WorldEntity[];
  zones: Array<Record<string, any>>;
  recent_events: WorldEvent[];
}

export interface ScenarioDefinition {
  key: string;
  name: string;
  description: string;
  map_width: number;
  map_height: number;
  zones: Array<Record<string, any>>;
  initial_entities: Array<Record<string, any>>;
  scripted_events: Array<Record<string, any>>;
  mission_goal: string;
  tags: string[];
}

export interface DashboardSummary {
  agents: { total: number; active: number; idle: number; failed: number };
  missions: { active: number; total: number };
  tasks: { pending: number; in_progress: number; blocked: number; completed: number; failed: number };
  pending_approvals: number;
  sim_time: number;
  simulation_running: boolean;
  simulation_paused: boolean;
  active_scenario: string | null;
}

export interface PendingApproval {
  task_id: string;
  [key: string]: unknown;
}

export type WsEnvelope =
  | { type: 'snapshot'; data: { agents: AgentStatus[]; world: WorldSnapshot; summary: DashboardSummary; approvals: PendingApproval[] } }
  | { type: 'agent_state'; data: AgentStatus }
  | { type: 'agent_added'; data: AgentStatus }
  | { type: 'agent_removed'; data: { agent_id: string } }
  | { type: 'message'; data: Message }
  | { type: 'decision'; data: DecisionRecord }
  | { type: 'world_update'; data: WorldSnapshot }
  | { type: 'mission_progress'; data: MissionReport }
  | { type: 'approval_requested'; data: PendingApproval }
  | { type: string; data: unknown };
