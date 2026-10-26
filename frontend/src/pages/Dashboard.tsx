import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../api/client';
import { useStore } from '../api/store';
import type { Mission } from '../types';
import { Card, Stat, Button } from '../components/ui';
import { ApprovalsPanel } from '../components/ApprovalsPanel';

export default function Dashboard() {
  const { summary, agents, missionVersion } = useStore();
  const [missions, setMissions] = useState<Mission[]>([]);

  useEffect(() => {
    api.listMissions().then(setMissions).catch(() => {});
  }, [missionVersion]);

  const agentList = Object.values(agents);

  return (
    <div className="flex flex-col gap-4 p-4">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4 lg:grid-cols-6">
        <Stat label="Agents" value={summary?.agents.total ?? '—'} />
        <Stat label="Agents active" value={summary?.agents.active ?? '—'} tone="ok" />
        <Stat label="Agents failed" value={summary?.agents.failed ?? 0} tone={summary?.agents.failed ? 'bad' : undefined} />
        <Stat label="Missions active" value={summary?.missions.active ?? '—'} tone="ok" />
        <Stat label="Tasks in progress" value={summary?.tasks.in_progress ?? 0} />
        <Stat label="Pending approvals" value={summary?.pending_approvals ?? 0} tone={summary?.pending_approvals ? 'warn' : undefined} />
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <Card title="Missions" className="lg:col-span-2">
          {missions.length === 0 ? (
            <p className="text-sm text-neutral-500">No missions yet — start a scenario from the control bar above.</p>
          ) : (
            <table className="w-full text-xs">
              <thead className="text-neutral-500">
                <tr className="text-left">
                  <th className="pb-2">Name</th>
                  <th className="pb-2">Scenario</th>
                  <th className="pb-2">Status</th>
                  <th className="pb-2">Goal</th>
                  <th className="pb-2" />
                </tr>
              </thead>
              <tbody>
                {missions.slice().reverse().map((m) => (
                  <tr key={m.mission_id} className="border-t border-neutral-800">
                    <td className="py-1.5 pr-2 font-medium text-neutral-200">{m.name}</td>
                    <td className="py-1.5 pr-2 text-neutral-400">{m.scenario_key}</td>
                    <td className="py-1.5 pr-2">
                      <StatusPill status={m.status} />
                    </td>
                    <td className="max-w-xs truncate py-1.5 pr-2 text-neutral-400">{m.goal}</td>
                    <td className="py-1.5 text-right">
                      <Link to={`/missions/${m.mission_id}`}>
                        <Button>Inspect</Button>
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>

        <ApprovalsPanel />
      </div>

      <Card title="Agent roster">
        <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
          {agentList.map((a) => (
            <Link
              key={a.agent_id}
              to="/agents"
              className="rounded-md border border-neutral-800 bg-neutral-950 px-3 py-2 hover:border-neutral-600"
            >
              <div className="text-xs font-medium text-neutral-200">{a.name}</div>
              <div className="text-[10px] uppercase text-neutral-500">{a.role}</div>
              <div className="mt-1 text-[10px] text-neutral-400">{a.state}</div>
            </Link>
          ))}
        </div>
      </Card>
    </div>
  );
}

function StatusPill({ status }: { status: string }) {
  const tone: Record<string, string> = {
    draft: 'bg-neutral-800 text-neutral-400',
    active: 'bg-emerald-900 text-emerald-300',
    paused: 'bg-amber-900 text-amber-300',
    completed: 'bg-indigo-900 text-indigo-300',
    failed: 'bg-rose-900 text-rose-300',
    cancelled: 'bg-neutral-800 text-neutral-500',
  };
  return <span className={`rounded px-1.5 py-0.5 text-[10px] font-medium uppercase ${tone[status] ?? ''}`}>{status}</span>;
}
