import { useCallback, useEffect, useState } from 'react';
import { api } from '../api/client';
import type { PendingApproval } from '../types';
import { Card, Button } from './ui';

// This panel polls /api/approvals directly rather than trusting the
// WebSocket store's `approvals` list: the backend broadcasts
// "approval_requested" when a new one is queued, but emits nothing when one
// is resolved via POST /api/approvals/{id} (see coordinator.authorize_pending),
// so a WS-only view would show a resolved approval as still pending until
// the next full snapshot. Polling + optimistic removal keeps this correct.
export function ApprovalsPanel() {
  const [approvals, setApprovals] = useState<PendingApproval[]>([]);
  const [busy, setBusy] = useState<string | null>(null);

  const refresh = useCallback(() => {
    api.listApprovals().then(setApprovals).catch(() => {});
  }, []);

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, 2500);
    return () => clearInterval(id);
  }, [refresh]);

  const decide = async (taskId: string, approve: boolean) => {
    setBusy(taskId);
    try {
      await api.decideApproval(taskId, approve);
      setApprovals((list) => list.filter((a) => a.task_id !== taskId));
    } catch {
      refresh();
    } finally {
      setBusy(null);
    }
  };

  return (
    <Card title={`Pending approvals${approvals.length ? ` (${approvals.length})` : ''}`}>
      {approvals.length === 0 ? (
        <p className="text-sm text-neutral-500">Nothing waiting on a human right now.</p>
      ) : (
        <div className="flex flex-col gap-2">
          {approvals.map((a) => (
            <div key={a.task_id} className="rounded-md border border-amber-900/50 bg-amber-950/20 p-2">
              <div className="text-xs font-medium text-amber-300">task {a.task_id}</div>
              <div className="mt-0.5 text-[11px] text-neutral-400">
                action: {String(a.selected_action ?? '—')}
                {a.reason ? ` · ${String(a.reason)}` : ''}
              </div>
              <div className="mt-2 flex gap-2">
                <Button variant="primary" disabled={busy === a.task_id} onClick={() => decide(a.task_id, true)}>
                  Approve
                </Button>
                <Button variant="danger" disabled={busy === a.task_id} onClick={() => decide(a.task_id, false)}>
                  Reject
                </Button>
              </div>
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}
