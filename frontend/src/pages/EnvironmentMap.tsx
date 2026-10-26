import { useMemo, useState } from 'react';
import { useStore } from '../api/store';
import type { WorldEntity } from '../types';
import { Card } from '../components/ui';

const KIND_COLOR: Record<string, string> = {
  bot: '#38bdf8',
  object: '#a3a3a3',
  zone: '#a78bfa',
  resource: '#34d399',
  hazard: '#fb7185',
};

const CELL = 42;
const PAD = 30;

// When two entities land on the same grid cell (a bot moving onto a
// resource it's holding, say), drawing them dead-center on top of each
// other makes one completely invisible -- the map's whole job is to show
// the environment visibly changing, so a hidden entity defeats that.
// Spread entities sharing a cell around a small circle instead.
function withCellOffsets(entities: WorldEntity[]): Array<{ entity: WorldEntity; dx: number; dy: number }> {
  const byCell = new Map<string, WorldEntity[]>();
  for (const e of entities) {
    const key = `${e.x},${e.y}`;
    const list = byCell.get(key) ?? [];
    list.push(e);
    byCell.set(key, list);
  }
  const out: Array<{ entity: WorldEntity; dx: number; dy: number }> = [];
  for (const group of byCell.values()) {
    const n = group.length;
    group.forEach((entity, i) => {
      if (n === 1) {
        out.push({ entity, dx: 0, dy: 0 });
      } else {
        const angle = (2 * Math.PI * i) / n;
        out.push({ entity, dx: Math.round(Math.cos(angle) * 10), dy: Math.round(Math.sin(angle) * 10) });
      }
    });
  }
  return out;
}

export default function EnvironmentMap() {
  const { world } = useStore();
  const [selected, setSelected] = useState<WorldEntity | null>(null);

  const w = world?.width ?? 10;
  const h = world?.height ?? 10;
  const entities = world?.entities ?? [];

  const svgW = w * CELL + PAD * 2;
  const svgH = h * CELL + PAD * 2;

  const grid = useMemo(() => {
    const lines: React.ReactNode[] = [];
    for (let i = 0; i <= w; i++) {
      lines.push(<line key={`v${i}`} x1={PAD + i * CELL} y1={PAD} x2={PAD + i * CELL} y2={PAD + h * CELL} stroke="#1f2028" />);
    }
    for (let j = 0; j <= h; j++) {
      lines.push(<line key={`h${j}`} x1={PAD} y1={PAD + j * CELL} x2={PAD + w * CELL} y2={PAD + j * CELL} stroke="#1f2028" />);
    }
    return lines;
  }, [w, h]);

  if (!world) {
    return <div className="p-4 text-sm text-neutral-500">No world loaded yet — start a scenario.</div>;
  }

  return (
    <div className="flex h-full gap-4 p-4">
      <Card title={`Map (${w}×${h}) · sim_time ${world.sim_time}`} className="flex-1 overflow-auto">
        <svg width={svgW} height={svgH} className="max-w-full">
          <rect x={0} y={0} width={svgW} height={svgH} fill="#0b0d12" />
          {grid}
          {withCellOffsets(entities).map(({ entity: e, dx, dy }) => {
            const cx = PAD + e.x * CELL + CELL / 2 + dx;
            const cy = PAD + e.y * CELL + CELL / 2 + dy;
            const blocked = Boolean(e.attributes?.blocked);
            const color = KIND_COLOR[e.kind] ?? '#eab308';
            return (
              <g key={e.entity_id} onClick={() => setSelected(e)} className="cursor-pointer">
                {e.kind === 'bot' ? (
                  <circle cx={cx} cy={cy} r={11} fill={color} stroke="#0b0d12" strokeWidth={2} />
                ) : (
                  <rect x={cx - 11} y={cy - 11} width={22} height={22} rx={4} fill={color} opacity={blocked ? 0.35 : 0.85}
                        stroke={blocked ? '#fb7185' : '#0b0d12'} strokeWidth={blocked ? 2 : 1} />
                )}
                {blocked && (
                  <text x={cx} y={cy + 3} textAnchor="middle" fontSize={11} fill="#fff1f2">✕</text>
                )}
                <text x={cx} y={cy + 24} textAnchor="middle" fontSize={10} fill="#9ca3af">{e.label}</text>
              </g>
            );
          })}
        </svg>
      </Card>

      <div className="flex w-72 flex-col gap-4">
        <Card title="Legend">
          <div className="flex flex-col gap-1 text-xs">
            {Object.entries(KIND_COLOR).map(([kind, color]) => (
              <div key={kind} className="flex items-center gap-2">
                <span className="inline-block h-2.5 w-2.5 rounded-sm" style={{ background: color }} />
                <span className="capitalize text-neutral-300">{kind}</span>
              </div>
            ))}
          </div>
        </Card>

        <Card title={selected ? `Entity: ${selected.label}` : 'Entity inspector'}>
          {selected ? (
            <div className="flex flex-col gap-1 text-xs text-neutral-300">
              <div><span className="text-neutral-500">id:</span> {selected.entity_id}</div>
              <div><span className="text-neutral-500">kind:</span> {selected.kind}</div>
              <div><span className="text-neutral-500">pos:</span> ({selected.x}, {selected.y})</div>
              <div><span className="text-neutral-500">zone:</span> {selected.zone_id ?? '—'}</div>
              <pre className="mt-1 max-h-48 overflow-auto rounded bg-neutral-950 p-2 text-[11px] text-neutral-400">
                {JSON.stringify(selected.attributes, null, 2)}
              </pre>
            </div>
          ) : (
            <p className="text-sm text-neutral-500">Click an entity on the map.</p>
          )}
        </Card>

        <Card title="Recent world events">
          <div className="flex max-h-72 flex-col gap-2 overflow-auto text-xs">
            {world.recent_events.length === 0 && <p className="text-neutral-500">No events yet.</p>}
            {world.recent_events.slice().reverse().map((ev) => (
              <div key={ev.event_id} className="rounded border border-neutral-800 bg-neutral-950 p-1.5">
                <div className="font-medium text-neutral-200">{ev.kind}</div>
                <div className="text-neutral-400">{ev.description}</div>
              </div>
            ))}
          </div>
        </Card>
      </div>
    </div>
  );
}
