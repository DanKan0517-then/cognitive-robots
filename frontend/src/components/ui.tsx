import React from 'react';
import clsx from 'clsx';
import type { AgentState } from '../types';

export function Card({ title, children, className, right }: {
  title?: string; children: React.ReactNode; className?: string; right?: React.ReactNode;
}) {
  return (
    <div className={clsx('rounded-lg border border-neutral-800 bg-neutral-900/60', className)}>
      {title && (
        <div className="flex items-center justify-between border-b border-neutral-800 px-3 py-2">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-neutral-400">{title}</h3>
          {right}
        </div>
      )}
      <div className="p-3">{children}</div>
    </div>
  );
}

export function Stat({ label, value, tone }: { label: string; value: React.ReactNode; tone?: 'ok' | 'warn' | 'bad' }) {
  return (
    <div className="flex flex-col gap-0.5 rounded-md border border-neutral-800 bg-neutral-950 px-3 py-2">
      <span className="text-[10px] uppercase tracking-wide text-neutral-500">{label}</span>
      <span
        className={clsx(
          'text-xl font-semibold tabular-nums',
          tone === 'ok' && 'text-emerald-400',
          tone === 'warn' && 'text-amber-400',
          tone === 'bad' && 'text-rose-400',
          !tone && 'text-neutral-100',
        )}
      >
        {value}
      </span>
    </div>
  );
}

const STATE_COLORS: Record<AgentState, string> = {
  idle: 'bg-neutral-700 text-neutral-200',
  observing: 'bg-sky-900 text-sky-300',
  reasoning: 'bg-violet-900 text-violet-300',
  planning: 'bg-indigo-900 text-indigo-300',
  negotiating: 'bg-fuchsia-900 text-fuchsia-300',
  executing: 'bg-amber-900 text-amber-300',
  verifying: 'bg-cyan-900 text-cyan-300',
  completed: 'bg-emerald-900 text-emerald-300',
  waiting_for_agent: 'bg-neutral-800 text-neutral-400',
  blocked: 'bg-orange-900 text-orange-300',
  failed: 'bg-rose-900 text-rose-300',
  recovering: 'bg-yellow-900 text-yellow-300',
  stopped: 'bg-neutral-800 text-neutral-500',
};

export function StateBadge({ state }: { state: AgentState }) {
  return (
    <span className={clsx('rounded px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide', STATE_COLORS[state] ?? 'bg-neutral-800')}>
      {state.replace(/_/g, ' ')}
    </span>
  );
}

export function HealthDot({ health }: { health: string }) {
  return (
    <span
      className={clsx(
        'inline-block h-2 w-2 rounded-full',
        health === 'healthy' && 'bg-emerald-500',
        health === 'degraded' && 'bg-amber-500',
        health === 'unresponsive' && 'bg-rose-500',
      )}
      title={health}
    />
  );
}

export function Button({ children, className, variant = 'default', ...rest }: React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: 'default' | 'primary' | 'danger' }) {
  return (
    <button
      {...rest}
      className={clsx(
        'rounded-md px-2.5 py-1.5 text-xs font-medium transition disabled:cursor-not-allowed disabled:opacity-40',
        variant === 'default' && 'bg-neutral-800 text-neutral-200 hover:bg-neutral-700',
        variant === 'primary' && 'bg-indigo-600 text-white hover:bg-indigo-500',
        variant === 'danger' && 'bg-rose-700 text-white hover:bg-rose-600',
        className,
      )}
    >
      {children}
    </button>
  );
}

export function timeAgo(iso: string | null | undefined): string {
  if (!iso) return '—';
  const diff = Date.now() - new Date(iso).getTime();
  if (diff < 1000) return 'now';
  if (diff < 60_000) return `${Math.floor(diff / 1000)}s ago`;
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)}m ago`;
  return `${Math.floor(diff / 3_600_000)}h ago`;
}
