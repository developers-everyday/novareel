import { auth } from '@clerk/nextjs/server';
import { ProjectStudio } from '@/components/project-studio';

export default async function DashboardPage() {
  const { userId } = await auth();

  if (!userId) {
    return null;
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight text-ink">Video Studio</h1>
        <p className="mt-2 text-slate-600">Generate conversion-focused product videos with asynchronous processing and live status updates.</p>
      </div>
      <ProjectStudio />
    </div>
  );
}
