import { auth } from '@clerk/nextjs/server';
import { AdminOverviewPanel } from '@/components/admin-overview';

export default async function AdminPage() {
  const { userId } = await auth();

  if (!userId) {
    return null;
  }

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-3xl font-bold tracking-tight text-ink">Admin Overview</h1>
        <p className="mt-2 text-slate-600">Private beta activation and generation health for the current rollout month.</p>
      </div>
      <AdminOverviewPanel />
    </div>
  );
}
