import Link from 'next/link';
import { UserButton } from '@clerk/nextjs';

export default function AppLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen">
      <header className="border-b border-slate-200/70 bg-white/90 backdrop-blur">
        <div className="container flex h-16 items-center justify-between">
          <Link href="/" className="font-semibold text-ink">
            NovaReel
          </Link>
          <div className="flex items-center gap-3">
            <Link href="/app/dashboard" className="text-sm text-slate-600 hover:text-ink">
              Dashboard
            </Link>
            <Link href="/app/admin" className="text-sm text-slate-600 hover:text-ink">
              Admin
            </Link>
            <Link href="/pricing" className="text-sm text-slate-600 hover:text-ink">
              Pricing
            </Link>
            <UserButton />
          </div>
        </div>
      </header>
      <main className="container py-8">{children}</main>
    </div>
  );
}
