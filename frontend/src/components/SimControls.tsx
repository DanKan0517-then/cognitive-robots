import { useEffect, useState } from 'react';
import { api } from '../api/client';
import { useStore } from '../api/store';
import type { ScenarioDefinition } from '../types';
import { Button } from './ui';

export function SimControls() {
  const { summary } = useStore();
  const [scenarios, setScenarios] = useState<ScenarioDefinition[]>([]);
  const [selected, setSelected] = useState<string>('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.listScenarios().then((s) => {
      setScenarios(s);
      if (s.length && !selected) setSelected(s[0].key);
    }).catch((e) => setError(String(e)));
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const act = async (fn: () => Promise<unknown>) => {
    setBusy(true);
    setError(null);
    try {
      await fn();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  };

  const running = summary?.simulation_running ?? false;
  const paused = summary?.simulation_paused ?? false;

  return (
    <div className="flex flex-wrap items-center gap-2 border-b border-neutral-800 bg-neutral-950 px-4 py-2">
      <select
        value={selected}
        onChange={(e) => setSelected(e.target.value)}
        className="rounded-md border border-neutral-700 bg-neutral-900 px-2 py-1.5 text-xs text-neutral-200"
      >
        {scenarios.map((s) => (
          <option key={s.key} value={s.key}>{s.name}</option>
        ))}
      </select>
      <Button variant="primary" disabled={busy || !selected} onClick={() => act(() => api.startSimulation(selected))}>
        ▶ Start scenario
      </Button>
      <div className="mx-1 h-5 w-px bg-neutral-800" />
      {!paused ? (
        <Button disabled={busy || !running} onClick={() => act(() => api.pauseSimulation())}>⏸ Pause</Button>
      ) : (
        <Button disabled={busy || !running} onClick={() => act(() => api.resumeSimulation())}>▶ Resume</Button>
      )}
      <Button disabled={busy || !running} onClick={() => act(() => api.stepSimulation())}>⏭ Step</Button>
      <Button variant="danger" disabled={busy} onClick={() => act(() => api.resetSimulation())}>⟲ Reset</Button>
      <div className="mx-1 h-5 w-px bg-neutral-800" />
      <label className="flex items-center gap-1 text-xs text-neutral-400">
        Speed
        <select
          defaultValue="1"
          onChange={(e) => act(() => api.setSpeed(Number(e.target.value)))}
          className="rounded-md border border-neutral-700 bg-neutral-900 px-1.5 py-1 text-xs text-neutral-200"
        >
          {[0.5, 1, 2, 5, 10].map((s) => <option key={s} value={s}>{s}×</option>)}
        </select>
      </label>

      <div className="ml-auto flex items-center gap-3 text-xs text-neutral-400">
        <span>sim_time: <span className="tabular-nums text-neutral-200">{summary?.sim_time ?? 0}</span></span>
        <span className={running ? (paused ? 'text-amber-400' : 'text-emerald-400') : 'text-neutral-500'}>
          {running ? (paused ? 'paused' : 'running') : 'stopped'}
        </span>
        {summary?.active_scenario && <span className="text-neutral-500">· {summary.active_scenario}</span>}
      </div>

      {error && <div className="w-full text-xs text-rose-400">{error}</div>}
    </div>
  );
}
