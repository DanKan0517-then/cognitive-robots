import { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { api } from '../api/client';
import { useStore } from '../api/store';
import type { Mission, MissionReport } from '../types';
import { Card, Button, timeAgo } from '../components/ui';

export default function MissionInspector() {
  const { missionId } = useParams();
  const { missionVersion } = useStore();
  const [missions, setMissions] = useState<Mission[]>([]);
  const [selectedId, setSelectedId] = useState<string | undefined>(missionId);
  const [report, setReport] = useState<MissionReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.listMissions().then((list) => {
      setMissions(list);
      if (!selectedId && list.length) setSelectedId(list[list.length - 1].mission_id);
    }).catch(() => {});
  }, [missionVersion]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!selectedId) return;
    let cancelled = false;
    const load = () => {
      api.getMission(selectedId).then((r) => { if (!cancelled) setReport(r); }).catch((e) => setError(String(e)));
    };
    load();
    const id = setInterval(load, 2000);
    return () => { cancelled = true; clearInterval(id); };
  }, [selectedId, missionVersion]);

  const doExport = async () => {
    if (!selectedId) return;
    setBusy(true);
    try {
      const full = await api.exportMission(selectedId);
      const blob = new Blob([JSON.stringify(full, null, 2)], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `mission-${selectedId}.json`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex h-full gap-4 p-4">
      <Card title="Missions" className="w-72 shrink-0 overflow-auto">
        <div className="flex flex-col gap-1.5">
          {missions.slice().reverse().map((m) => (
            <Link
              key={m.mission_id}
              to={`/missions/${m.mission_id}`}
              onClick={() => setSelectedId(m.mission_id)}
              className={`rounded-md border px-2.5 py-2 text-xs ${
                selectedId === m.mission_id ? 'border-indigo-600 bg-indigo-950/40' : 'border-neutral-800 bg-neutral-950 hover:border-neutral-600'
              }`}
            >
              <div className="font-medium text-neutral-200">{m.name}</div>
              <div className="text-[10px] uppercase text-neutral-500">{m.status}</div>
            </Link>
          ))}
        </div>
      </Card>

      <div className="flex-1 overflow-auto">
        {error && <div className="mb-2 text-xs text-rose-400">{error}</div>}
        {!report ? (
          <div className="p-4 text-sm text-neutral-500">Select a mission.</div>
        ) : (
          <div className="flex flex-col gap-4">
            <Card title={report.mission.name} right={<Button onClick={doExport} disabled={busy}>⬇ Export log</Button>}>
              <div className="grid grid-cols-2 gap-3 text-xs md:grid-cols-4">
                <Field label="Status" value={report.mission.status} />
                <Field label="Scenario" value={report.mission.scenario_key} />
                <Field label="Progress" value={`${report.progress.completed} / ${report.progress.total} tasks`} />
                <Field label="Outcome" value={report.mission.outcome ?? '—'} />
                <Field label="Goal" value={report.mission.goal} wide />
                <Field label="Created" value={timeAgo(report.mission.created_at)} />
                <Field label="Updated" value={timeAgo(report.mission.updated_at)} />
              </div>
              <div className="mt-3 flex gap-2">
                <Button
                  disabled={report.mission.status === 'cancelled' || report.mission.status === 'completed'}
                  variant="danger"
                  onClick={() => api.cancelMission(report.mission.mission_id).then(() => setSelectedId(selectedId))}
                >
                  Cancel mission
                </Button>
                <Button onClick={() => api.retryMission(report.mission.mission_id)}>
                  Retry failed tasks
                </Button>
              </div>
            </Card>

            <Card title={`Tasks (${report.tasks.length})`}>
              <table className="w-full text-xs">
                <thead className="text-neutral-500">
                  <tr className="text-left">
                    <th className="pb-1">Title</th>
                    <th className="pb-1">Status</th>
                    <th className="pb-1">Agent</th>
                    <th className="pb-1">Retries</th>
                    <th className="pb-1">Error</th>
                  </tr>
                </thead>
                <tbody>
                  {report.tasks.map((t) => (
                    <tr key={t.task_id} className="border-t border-neutral-800">
                      <td className="py-1.5 pr-2 font-medium text-neutral-200">{t.title}</td>
                      <td className="py-1.5 pr-2"><TaskStatusTag status={t.status} /></td>
                      <td className="py-1.5 pr-2 text-neutral-400">{t.assigned_agent_id ?? '—'}</td>
                      <td className="py-1.5 pr-2 text-neutral-400">{t.retries}/{t.max_retries}</td>
                      <td className="max-w-xs truncate py-1.5 text-rose-400">{t.error ?? ''}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Card>
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

function TaskStatusTag({ status }: { status: string }) {
  const tone: Record<string, string> = {
    pending: 'text-neutral-400', assigned: 'text-sky-400', in_progress: 'text-amber-400',
    blocked: 'text-orange-400', completed: 'text-emerald-400', failed: 'text-rose-400', cancelled: 'text-neutral-500',
  };
  return <span className={`uppercase ${tone[status] ?? ''}`}>{status}</span>;
}
