import type { GenerationJob } from '@/lib/contracts';

const stageCopy: Record<string, string> = {
  queued: 'Queued for processing',
  analyzing: 'Analyzing product images',
  scripting: 'Generating storyboard script',
  matching: 'Matching product images with script',
  narration: 'Synthesizing voice narration',
  rendering: 'Rendering final video',
  completed: 'Completed',
  failed: 'Failed',
  loading: 'Loading source video data',
  translating: 'Translating script',
  awaiting_approval: 'Awaiting storyboard approval',
};

export function JobStatusCard({ job }: { job: GenerationJob }) {
  const progress = Math.max(0, Math.min(job.progress_pct, 100));

  return (
    <section className="surface p-5">
      <div className="mb-3 flex items-center justify-between">
        <h3 className="text-lg font-semibold text-ink">Generation Job</h3>
        <span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-medium text-slate-700">{job.status}</span>
      </div>

      <p className="text-sm text-slate-600">{stageCopy[job.stage] ?? 'Processing'}</p>
      <div className="mt-4 h-2 rounded-full bg-slate-200">
        <div className="h-full rounded-full bg-ember transition-all" style={{ width: `${progress}%` }} />
      </div>
      <p className="mt-2 text-sm text-slate-700">{progress}%</p>
      {job.error_code ? <p className="mt-2 text-sm text-red-600">Error: {job.error_code}</p> : null}
    </section>
  );
}
