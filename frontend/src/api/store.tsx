import React, { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react';
import { api } from './client';
import type {
  AgentStatus, DashboardSummary, DecisionRecord, Message, PendingApproval, WorldSnapshot, WsEnvelope,
} from '../types';

interface StoreState {
  connected: boolean;
  agents: Record<string, AgentStatus>;
  world: WorldSnapshot | null;
  summary: DashboardSummary | null;
  approvals: PendingApproval[];
  messages: Message[]; // most recent first, capped
  decisions: DecisionRecord[]; // most recent first, capped
  missionVersion: number; // bumped on every mission_progress event, for views to refetch
}

const MAX_MESSAGES = 500;
const MAX_DECISIONS = 300;

const StoreContext = createContext<StoreState | null>(null);

function wsUrl(): string {
  const proto = window.location.protocol === 'https:' ? 'wss' : 'ws';
  return `${proto}://${window.location.host}/ws`;
}

export function StoreProvider({ children }: { children: React.ReactNode }) {
  const [state, setState] = useState<StoreState>({
    connected: false,
    agents: {},
    world: null,
    summary: null,
    approvals: [],
    messages: [],
    decisions: [],
    missionVersion: 0,
  });
  const wsRef = useRef<WebSocket | null>(null);
  const retryRef = useRef<number>(0);

  const connect = useCallback(() => {
    const ws = new WebSocket(wsUrl());
    wsRef.current = ws;

    ws.onopen = () => {
      retryRef.current = 0;
      setState((s) => ({ ...s, connected: true }));
    };

    ws.onclose = () => {
      setState((s) => ({ ...s, connected: false }));
      // Reconnect with capped backoff — the sim keeps running server-side
      // whether or not a client is watching, so a dropped client just needs
      // to catch back up via the next snapshot.
      const delay = Math.min(1000 * 2 ** retryRef.current, 10_000);
      retryRef.current += 1;
      setTimeout(connect, delay);
    };

    ws.onerror = () => {
      ws.close();
    };

    ws.onmessage = (ev) => {
      let envelope: WsEnvelope;
      try {
        envelope = JSON.parse(ev.data);
      } catch {
        return;
      }
      setState((s) => applyEnvelope(s, envelope));
    };
  }, []);

  useEffect(() => {
    connect();
    return () => wsRef.current?.close();
  }, [connect]);

  useEffect(() => {
    // The WS stream only ever pushes events that happen *after* a client
    // connects — the initial "snapshot" envelope carries agents/world/
    // summary/approvals but not message or decision history. Without this,
    // the Communication Center and Agent Control Room show nothing until
    // new activity happens to occur after the page was opened, even though
    // the backend already has plenty of history via REST. Seed once on
    // mount, oldest-first REST results reversed to match the newest-first
    // store, deduped against anything the WS has already delivered.
    Promise.all([api.listMessages({ limit: MAX_MESSAGES }), api.listDecisions({ limit: MAX_DECISIONS })])
      .then(([msgs, decisions]) => {
        setState((s) => ({
          ...s,
          messages: mergeNewestFirst(s.messages, msgs.slice().reverse(), (m) => m.message_id).slice(0, MAX_MESSAGES),
          decisions: mergeNewestFirst(s.decisions, decisions.slice().reverse(), (d) => d.decision_id).slice(0, MAX_DECISIONS),
        }));
      })
      .catch(() => {
        /* backend may not be up yet on first mount; WS will still connect and keep the page live */
      });
  }, []);

  return <StoreContext.Provider value={state}>{children}</StoreContext.Provider>;
}

function mergeNewestFirst<T extends { timestamp: string }>(
  existingNewestFirst: T[], incomingNewestFirst: T[], idOf: (t: T) => string,
): T[] {
  const seen = new Set(existingNewestFirst.map(idOf));
  const merged = existingNewestFirst.slice();
  for (const item of incomingNewestFirst) {
    if (!seen.has(idOf(item))) {
      merged.push(item);
      seen.add(idOf(item));
    }
  }
  merged.sort((a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime());
  return merged;
}

function applyEnvelope(s: StoreState, envelope: WsEnvelope): StoreState {
  switch (envelope.type) {
    case 'snapshot': {
      const data = envelope.data as any;
      const agents: Record<string, AgentStatus> = {};
      for (const a of data.agents as AgentStatus[]) agents[a.agent_id] = a;
      return { ...s, agents, world: data.world, summary: data.summary, approvals: data.approvals };
    }
    case 'agent_state':
    case 'agent_added': {
      const a = envelope.data as AgentStatus;
      return { ...s, agents: { ...s.agents, [a.agent_id]: a } };
    }
    case 'agent_removed': {
      const { agent_id } = envelope.data as { agent_id: string };
      const agents = { ...s.agents };
      delete agents[agent_id];
      return { ...s, agents };
    }
    case 'message': {
      const m = envelope.data as Message;
      return { ...s, messages: [m, ...s.messages].slice(0, MAX_MESSAGES) };
    }
    case 'decision': {
      const d = envelope.data as DecisionRecord;
      return { ...s, decisions: [d, ...s.decisions].slice(0, MAX_DECISIONS) };
    }
    case 'world_update': {
      return { ...s, world: envelope.data as WorldSnapshot };
    }
    case 'mission_progress': {
      return { ...s, missionVersion: s.missionVersion + 1 };
    }
    case 'approval_requested': {
      const approval = envelope.data as PendingApproval;
      const exists = s.approvals.some((a) => a.task_id === approval.task_id);
      return { ...s, approvals: exists ? s.approvals : [...s.approvals, approval] };
    }
    default:
      return s;
  }
}

export function useStore(): StoreState {
  const ctx = useContext(StoreContext);
  if (!ctx) throw new Error('useStore must be used within StoreProvider');
  return ctx;
}
