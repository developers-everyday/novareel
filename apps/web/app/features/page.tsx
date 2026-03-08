import type { Metadata } from 'next';
import { SiteFooter } from '@/components/site-footer';
import { SiteHeader } from '@/components/site-header';

export const metadata: Metadata = {
  title: 'Features',
  description: 'See how NovaReel automates scripting, image sequencing, narration, and rendering.'
};

const features = [
  {
    title: 'Scene-by-scene scripting',
    detail: 'Nova 2 Lite generates concise product-led scripts with hooks, proof points, and CTA endings.'
  },
  {
    title: 'Smart image matching',
    detail: 'Multimodal embeddings align each script line with the most relevant product photo.'
  },
  {
    title: 'Natural narration',
    detail: 'Nova 2 Sonic voices every segment with style controls and Polly fallback resilience.'
  },
  {
    title: 'Async rendering pipeline',
    detail: 'Queued jobs process reliably with progress polling and resumable status tracking.'
  },
  {
    title: 'Quota + usage tracking',
    detail: 'Per-account monthly usage powers manual billing while Stripe is deferred to Phase 2.'
  },
  {
    title: 'SEO-ready web surface',
    detail: 'Pre-rendered landing pages, metadata, sitemap, robots, and optimized image delivery.'
  }
];

export default function FeaturesPage() {
  return (
    <>
      <SiteHeader />
      <main className="container py-16">
        <h1 className="text-4xl font-bold tracking-tight text-ink">NovaReel Features</h1>
        <p className="mt-3 max-w-2xl text-slate-600">
          Phase 1 private beta focuses on a complete pipeline from upload to rendered video, with reliability and activation as primary goals.
        </p>

        <div className="mt-10 grid gap-4 md:grid-cols-2">
          {features.map((item) => (
            <article key={item.title} className="surface p-6">
              <h2 className="text-xl font-semibold text-ink">{item.title}</h2>
              <p className="mt-2 text-sm text-slate-600">{item.detail}</p>
            </article>
          ))}
        </div>
      </main>
      <SiteFooter />
    </>
  );
}
