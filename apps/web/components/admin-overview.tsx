'use client';

import { useAuth } from '@clerk/nextjs';
import { useEffect, useState } from 'react';
import { getAdminDeadLetters, getAdminOverview } from '@/lib/api';
import type { AdminOverview, GenerationJob } from '@/lib/contracts';

function MetricCard({ label, value }: { label: string; value: string | number }) {
  return (
    <article className="surface p-4">
      <p className="text-xs uppercase tracking-wide text-slate-500">{label}</p>
      <p className="mt-2 text-2xl font-semibold text-ink">{value}</p>
    </article>
  );
}

export function AdminOverviewPanel() {
  const { getToken } = useAuth();
  const [data, setData] = useState<AdminOverview | null>(null);
  const [deadLetters, setDeadLetters] = useState<GenerationJob[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  async function loadOverview() {
    setLoading(true);
    setError(null);

    try {
      const token = await getToken();
      const [overview, deadLetterJobs] = await Promise.all([getAdminOverview(token), getAdminDeadLetters(token)]);
      setData(overview);
      setDeadLetters(deadLetterJobs);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load admin overview');
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadOverview().catch(() => undefined);
  }, []);

  if (loading) {
    return <p className="text-sm text-slate-600">Loading admin metrics...</p>;
  }

  if (error) {
    return <p className="rounded-lg bg-red-50 p-3 text-sm text-red-600">{error}</p>;
  }

  if (!data) {
    return <p className="text-sm text-slate-600">No metrics available.</p>;
  }

  return (
    <div className="space-y-6">
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <MetricCard label="Month" value={data.month} />
        <MetricCard label="Activation Rate" value={`${data.activation_rate_pct}%`} />
        <MetricCard label="Active Creators" value={data.active_creators} />
        <MetricCard label="Activated Creators" value={data.activated_creators} />
        <MetricCard label="Total Projects" value={data.total_projects} />
        <MetricCard label="Total Jobs" value={data.total_jobs} />
        <MetricCard label="Successful Jobs" value={data.successful_jobs} />
        <MetricCard label="Failed Jobs" value={data.failed_jobs} />
        <MetricCard label="Dead-Letter Jobs" value={data.dead_letter_jobs} />
      </div>

      <section className="surface p-5">
        <h2 className="text-lg font-semibold text-ink">Recent Jobs</h2>
        {data.recent_jobs.length === 0 ? (
          <p className="mt-2 text-sm text-slate-600">No recent jobs yet.</p>
        ) : (
          <div className="mt-3 overflow-x-auto">
            <table className="w-full min-w-[620px] text-sm">
              <thead>
                <tr className="text-left text-slate-500">
                  <th className="pb-2">Job</th>
                  <th className="pb-2">Project</th>
                  <th className="pb-2">Status</th>
                  <th className="pb-2">Progress</th>
                  <th className="pb-2">Updated</th>
                </tr>
              </thead>
              <tbody>
                {data.recent_jobs.map((job) => (
                  <tr key={job.id} className="border-t border-slate-100">
                    <td className="py-2 font-mono text-xs text-slate-700">{job.id.slice(0, 8)}</td>
                    <td className="py-2 font-mono text-xs text-slate-700">{job.project_id.slice(0, 8)}</td>
                    <td className="py-2 capitalize">{job.status}</td>
                    <td className="py-2">{job.progress_pct}%</td>
                    <td className="py-2 text-slate-600">{new Date(job.updated_at).toLocaleString()}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="surface p-5">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-lg font-semibold text-ink">Recent Analytics Events</h2>
          <button
            type="button"
            onClick={() => loadOverview().catch(() => undefined)}
            className="rounded-lg border border-slate-300 px-3 py-1 text-xs font-medium text-slate-700 hover:bg-slate-50"
          >
            Refresh
          </button>
        </div>

        {data.recent_events.length === 0 ? (
          <p className="text-sm text-slate-600">No analytics events yet.</p>
        ) : (
          <ul className="space-y-2 text-sm">
            {data.recent_events.map((event) => (
              <li key={event.id} className="rounded-lg border border-slate-100 p-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <p className="font-medium text-ink">{event.event_name}</p>
                  <p className="text-xs text-slate-500">{new Date(event.created_at).toLocaleString()}</p>
                </div>
                <p className="mt-1 text-xs text-slate-500">
                  owner={event.owner_id} project={event.project_id ?? '-'} job={event.job_id ?? '-'}
                </p>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="surface p-5">
        <h2 className="text-lg font-semibold text-ink">Dead-Letter Queue</h2>
        {deadLetters.length === 0 ? (
          <p className="mt-2 text-sm text-slate-600">No dead-lettered jobs.</p>
        ) : (
          <ul className="mt-3 space-y-2 text-sm">
            {deadLetters.map((job) => (
              <li key={job.id} className="rounded-lg border border-slate-100 p-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <p className="font-mono text-xs text-slate-700">{job.id}</p>
                  <p className="text-xs text-red-600">{job.dead_letter_reason ?? 'unknown_error'}</p>
                </div>
                <p className="mt-1 text-xs text-slate-500">
                  project={job.project_id} attempts={job.attempt_count}/{job.max_attempts}
                </p>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
