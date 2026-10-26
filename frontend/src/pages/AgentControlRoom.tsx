import { useEffect, useState } from 'react';
import { api } from '../api/client';
import { useStore } from '../api/store';
import type { AgentDetail } from '../types';
import { Card, StateBadge, HealthDot, timeAgo, Button } from '../components/ui';

export default function AgentControlRoom() {
  const { agents } = useStore();
  const list = Object.values(agents).sort((a, b) => a.role.localeCompare(b.role));
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<AgentDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!selectedId && list.length) setSelectedId(list[0].agent_id);
  }, [list, selectedId]);

  useEffect(() => {
    if (!selectedId) return;
    let cancelled = false;
    const load = () => {
      api.getAgent(selectedId).then((d) => { if (!cancelled) setDetail(d); }).catch((e) => setError(String(e)));
    };
    load();
    const id = setInterval(load, 2000);
    return () => { cancelled = true; clearInterval(id); };
  }, [selectedId]);

  return (
    <div className="flex h-full gap-4 p-4">
      <Card title={`Agents (${list.length})`} className="w-80 shrink-0 overflow-auto">
        <div className="flex flex-col gap-1.5">
          {list.map((a) => (
            <button
              key={a.agent_id}
              onClick={() => setSelectedId(a.agent_id)}
              className={`flex items-center justify-between rounded-md border px-2.5 py-2 text-left text-xs transition ${
                selectedId === a.agent_id ? 'border-indigo-600 bg-indigo-950/40' : 'border-neutral-800 bg-neutral-950 hover:border-neutral-600'
              }`}
            >
              <div>
                <div className="flex items-center gap-1.5 font-medium text-neutral-200">
                  <HealthDot health={a.health} />
                  {a.name}
                </div>
                <div className="text-[10px] uppercase text-neutral-500">{a.role}</div>
              </div>
              <StateBadge state={a.state} />
            </button>
          ))}
        </div>
      </Card>

      <div className="flex-1 overflow-auto">
        {error && <div className="mb-2 text-xs text-rose-400">{error}</div>}
        {!detail ? (
          <div className="p-4 text-sm text-neutral-500">Select an agent.</div>
        ) : (
          <div className="flex flex-col gap-4">
            <Card title={`${detail.status.name} — ${detail.status.role}`} right={<StateBadge state={detail.status.state} />}>
              <div className="grid grid-cols-2 gap-3 text-xs md:grid-cols-4">
                <Field label="Objective" value={detail.status.objective || '—'} wide />
                <Field label="Health" value={detail.status.health} />
                <Field label="Current task" value={detail.status.current_task_id ?? '—'} />
                <Field label="Msgs sent / recv" value={`${detail.status.messages_sent} / ${detail.status.messages_received}`} />
                <Field label="Decisions made" value={detail.status.decisions_made} />
                <Field label="Capabilities" value={detail.config.capabilities.join(', ') || '—'} wide />
                <Field label="Timeout (s)" value={detail.config.timeout_seconds} />
                <Field label="Max retries" value={detail.config.max_retries} />
                <Field label="Last updated" value={timeAgo(detail.status.last_updated)} />
                <Field label="Error" value={detail.status.error ?? '—'} wide />
              </div>
            </Card>

            {detail.blockers.length > 0 && (
              <Card title="Active blockers">
                <ul className="flex flex-col gap-1 text-xs text-amber-300">
                  {detail.blockers.map((b, i) => <li key={i}>⚠ {b}</li>)}
                </ul>
              </Card>
            )}

            <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
              <Card title="Recent observations">
                <ul className="flex max-h-64 flex-col gap-1.5 overflow-auto text-xs text-neutral-300">
                  {detail.recent_observations.length === 0 && <li className="text-neutral-500">None yet.</li>}
                  {detail.recent_observations.slice().reverse().map((o, i) => <li key={i} className="border-b border-neutral-900 pb-1">{o}</li>)}
                </ul>
              </Card>

              <Card title="Recent decisions">
                <ul className="flex max-h-64 flex-col gap-2 overflow-auto text-xs">
                  {detail.recent_decisions.length === 0 && <li className="text-neutral-500">None yet.</li>}
                  {detail.recent_decisions.slice().reverse().map((d) => (
                    <li key={d.decision_id} className="rounded border border-neutral-800 bg-neutral-950 p-2">
                      <div className="flex justify-between text-neutral-200">
                        <span className="font-medium">{d.selected_action ?? d.objective}</span>
                        <span className="tabular-nums text-neutral-500">{(d.confidence * 100).toFixed(0)}%</span>
                      </div>
                      <div className="mt-1 text-neutral-400">{d.rationale}</div>
                    </li>
                  ))}
                </ul>
              </Card>
            </div>

            <Card title="Recent messages (this agent)">
              <ul className="flex max-h-64 flex-col gap-1 overflow-auto text-xs">
                {detail.recent_messages.length === 0 && <li className="text-neutral-500">None yet.</li>}
                {detail.recent_messages.slice().reverse().map((m) => (
                  <li key={m.message_id} className="flex justify-between border-b border-neutral-900 py-1 text-neutral-300">
                    <span>{m.sender_id === detail.status.agent_id ? '→' : '←'} {m.message_type}</span>
                    <span className="text-neutral-500">{timeAgo(m.timestamp)}</span>
                  </li>
                ))}
              </ul>
            </Card>

            <div>
              <Button onClick={() => api.removeAgent(detail.status.agent_id).then(() => setSelectedId(null))} variant="danger">
                Remove agent
              </Button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function Field({ label, value, wide }: { label: string; value: React.ReactNode; wide?: boolean }) {
  return (
    <div className={wide ? 'col-span-2 md:col-span-4' : ''}>
      <div className="text-[10px] uppercase text-neutral-500">{label}</div>
      <div className="text-neutral-200">{value}</div>
    </div>
  );
}
