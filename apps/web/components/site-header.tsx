import Link from 'next/link';
import { SignedIn, SignedOut, SignInButton, UserButton } from '@clerk/nextjs';

export function SiteHeader() {
  return (
    <header className="sticky top-0 z-50 border-b border-slate-200/70 bg-white/85 backdrop-blur">
      <div className="container flex h-16 items-center justify-between">
        <Link href="/" className="font-semibold tracking-tight text-ink">
          NovaReel
        </Link>

        <nav className="hidden gap-6 text-sm text-slate-700 md:flex">
          <Link href="/features" className="hover:text-ink">
            Features
          </Link>
          <Link href="/pricing" className="hover:text-ink">
            Pricing
          </Link>
        </nav>

        <div className="flex items-center gap-3">
          <SignedOut>
            <SignInButton mode="modal">
              <button className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50">
                Sign in
              </button>
            </SignInButton>
          </SignedOut>
          <SignedIn>
            <Link
              href="/app/dashboard"
              className="rounded-lg bg-ink px-4 py-2 text-sm font-medium text-white hover:bg-slate-800"
            >
              Dashboard
            </Link>
            <UserButton />
          </SignedIn>
        </div>
      </div>
    </header>
  );
}
