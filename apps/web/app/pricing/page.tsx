import type { Metadata } from 'next';
import { SiteFooter } from '@/components/site-footer';
import { SiteHeader } from '@/components/site-header';

export const metadata: Metadata = {
  title: 'Pricing',
  description: 'NovaReel beta pricing and manual billing approach for Phase 1 rollout.'
};

const plans = [
  { name: 'Free', price: '$0', videos: '2 / month', features: 'Watermark, 720p' },
  { name: 'Starter', price: '$29', videos: '10 / month', features: 'No watermark, 1080p' },
  { name: 'Professional', price: '$79', videos: '50 / month', features: 'Custom branding, analytics' },
  { name: 'Enterprise', price: '$199', videos: 'Unlimited', features: 'White-label, API access' }
];

export default function PricingPage() {
  return (
    <>
      <SiteHeader />
      <main className="container py-16">
        <h1 className="text-4xl font-bold tracking-tight text-ink">Pricing</h1>
        <p className="mt-3 max-w-2xl text-slate-600">
          During Phase 1, billing is handled manually for beta customers while usage and quota are tracked in-product.
        </p>

        <div className="mt-10 grid gap-4 md:grid-cols-2 lg:grid-cols-4">
          {plans.map((plan) => (
            <article key={plan.name} className="surface p-6">
              <h2 className="text-xl font-semibold text-ink">{plan.name}</h2>
              <p className="mt-2 text-3xl font-bold">{plan.price}</p>
              <p className="mt-1 text-sm text-slate-600">{plan.videos}</p>
              <p className="mt-4 text-sm text-slate-700">{plan.features}</p>
            </article>
          ))}
        </div>
      </main>
      <SiteFooter />
    </>
  );
}
