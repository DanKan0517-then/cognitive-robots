import { useMemo, useState } from 'react';
import ReactFlow, { Background, type Edge, type Node } from 'reactflow';
import 'reactflow/dist/style.css';
import { useStore } from '../api/store';
import type { Message } from '../types';
import { Card, timeAgo } from '../components/ui';

const ROLE_ANGLE_LAYOUT: Record<string, { x: number; y: number }> = {
  perception: { x: 0, y: 0 },
  world_model: { x: 200, y: 0 },
  reasoning: { x: 400, y: 0 },
  planning: { x: 400, y: 160 },
  critic: { x: 200, y: 160 },
  coordinator: { x: 0, y: 160 },
  executor: { x: 0, y: 320 },
  memory: { x: 200, y: 320 },
};

export default function CommunicationCenter() {
  const { messages, agents } = useStore();
  const [typeFilter, setTypeFilter] = useState<string>('');
  const [agentFilter, setAgentFilter] = useState<string>('');
  const [selected, setSelected] = useState<Message | null>(null);

  const filtered = useMemo(() => {
    return messages.filter((m) =>
      (!typeFilter || m.message_type === typeFilter) &&
      (!agentFilter || m.sender_id === agentFilter || m.receiver_id === agentFilter));
  }, [messages, typeFilter, agentFilter]);

  const trace = useMemo(() => {
    if (!selected) return [];
    return messages.filter((m) => m.correlation_id === selected.correlation_id).slice().reverse();
  }, [selected, messages]);

  const { nodes, edges } = useMemo(() => buildGraph(messages.slice(0, 80), agents), [messages, agents]);

  const types = Array.from(new Set(messages.map((m) => m.message_type))).sort();

  return (
    <div className="flex h-full gap-4 p-4">
      <div className="flex w-[420px] shrink-0 flex-col gap-4">
        <Card title="Live message log" right={
          <div className="flex gap-1.5">
            <select value={agentFilter} onChange={(e) => setAgentFilter(e.target.value)}
                    className="rounded border border-neutral-700 bg-neutral-900 px-1 py-0.5 text-[10px] text-neutral-300">
              <option value="">all agents</option>
              {Object.values(agents).map((a) => <option key={a.agent_id} value={a.agent_id}>{a.name}</option>)}
            </select>
            <select value={typeFilter} onChange={(e) => setTypeFilter(e.target.value)}
                    className="rounded border border-neutral-700 bg-neutral-900 px-1 py-0.5 text-[10px] text-neutral-300">
              <option value="">all types</option>
              {types.map((t) => <option key={t} value={t}>{t}</option>)}
            </select>
          </div>
        }>
          <div className="flex max-h-[70vh] flex-col gap-1 overflow-auto text-xs">
            {filtered.length === 0 && <p className="text-neutral-500">No messages match.</p>}
            {filtered.map((m) => (
              <button
                key={m.message_id}
                onClick={() => setSelected(m)}
                className={`rounded border px-2 py-1.5 text-left ${
                  selected?.message_id === m.message_id ? 'border-indigo-600 bg-indigo-950/40' : 'border-neutral-800 bg-neutral-950 hover:border-neutral-600'
                }`}
              >
                <div className="flex justify-between">
                  <span className="font-medium text-neutral-200">{m.message_type}</span>
                  <span className="text-neutral-500">{timeAgo(m.timestamp)}</span>
                </div>
                <div className="text-neutral-400">
                  {agentName(agents, m.sender_id)} → {m.receiver_id ? agentName(agents, m.receiver_id) : 'broadcast'}
                </div>
                <PriorityTag priority={m.priority} status={m.status} />
              </button>
            ))}
          </div>
        </Card>
      </div>

      <div className="flex flex-1 flex-col gap-4">
        <Card title="Message flow graph (recent traffic)" className="h-80">
          <div className="h-64">
            <ReactFlow nodes={nodes} edges={edges} fitView proOptions={{ hideAttribution: true }}>
              <Background color="#1f2028" />
            </ReactFlow>
          </div>
        </Card>

        <Card title={selected ? `Trace — correlation ${selected.correlation_id}` : 'Message trace'} className="flex-1 overflow-auto">
          {!selected ? (
            <p className="text-sm text-neutral-500">Select a message from the log to see its full conversation trace.</p>
          ) : (
            <ol className="flex flex-col gap-2 text-xs">
              {trace.map((m, i) => (
                <li key={m.message_id} className="rounded border border-neutral-800 bg-neutral-950 p-2">
                  <div className="flex justify-between text-neutral-200">
                    <span>#{i + 1} {m.message_type} ({m.status})</span>
                    <span className="text-neutral-500">{timeAgo(m.timestamp)}</span>
                  </div>
                  <div className="mt-0.5 text-neutral-400">
                    {agentName(agents, m.sender_id)} → {m.receiver_id ? agentName(agents, m.receiver_id) : 'broadcast'}
                  </div>
                  <pre className="mt-1 overflow-auto rounded bg-black/40 p-1.5 text-[10px] text-neutral-500">
                    {JSON.stringify(m.payload, null, 2)}
                  </pre>
                </li>
              ))}
            </ol>
          )}
        </Card>
      </div>
    </div>
  );
}

function agentName(agents: Record<string, { name: string }>, id: string): string {
  return agents[id]?.name ?? id;
}

function PriorityTag({ priority, status }: { priority: string; status: string }) {
  const color = priority === 'critical' ? 'text-rose-400' : priority === 'high' ? 'text-amber-400' : 'text-neutral-500';
  return <div className={`mt-0.5 text-[10px] uppercase ${color}`}>{priority} · {status}</div>;
}

function buildGraph(recent: Message[], agents: Record<string, { name: string; role: string }>): { nodes: Node[]; edges: Edge[] } {
  const nodes: Node[] = Object.entries(agents).map(([id, a]) => ({
    id,
    position: ROLE_ANGLE_LAYOUT[a.role] ?? { x: Math.random() * 500, y: Math.random() * 300 },
    data: { label: a.name },
    style: {
      background: '#17181f', color: '#e5e7eb', border: '1px solid #30333d',
      borderRadius: 8, fontSize: 11, padding: 6, width: 140, textAlign: 'center' as const,
    },
  }));

  const counts = new Map<string, number>();
  for (const m of recent) {
    if (!m.receiver_id) continue;
    const key = `${m.sender_id}->${m.receiver_id}`;
    counts.set(key, (counts.get(key) ?? 0) + 1);
  }
  const edges: Edge[] = Array.from(counts.entries()).map(([key, count]) => {
    const [source, target] = key.split('->');
    return {
      id: key,
      source,
      target,
      label: String(count),
      animated: true,
      style: { stroke: '#4f46e5', strokeWidth: Math.min(1 + count / 2, 6) },
      labelStyle: { fill: '#9ca3af', fontSize: 10 },
    };
  });

  return { nodes, edges };
}
