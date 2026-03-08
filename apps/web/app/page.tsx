import Image from 'next/image';
import Link from 'next/link';
import { SiteFooter } from '@/components/site-footer';
import { SiteHeader } from '@/components/site-header';

const structuredData = {
  '@context': 'https://schema.org',
  '@type': 'SoftwareApplication',
  name: 'NovaReel',
  applicationCategory: 'BusinessApplication',
  operatingSystem: 'Web',
  description: 'AI video generator for ecommerce product listings powered by Amazon Nova.',
  offers: [
    { '@type': 'Offer', price: '0', priceCurrency: 'USD', name: 'Free' },
    { '@type': 'Offer', price: '29', priceCurrency: 'USD', name: 'Starter' }
  ]
};

export default function HomePage() {
  return (
    <>
      <SiteHeader />
      <main>
        <section className="container py-16 md:py-24">
          <div className="grid items-center gap-10 lg:grid-cols-2">
            <div>
              <p className="mb-4 inline-flex rounded-full bg-amber-100 px-3 py-1 text-xs font-semibold uppercase tracking-wide text-amber-700">
                Amazon Nova Private Beta
              </p>
              <h1 className="text-4xl font-bold tracking-tight text-ink md:text-6xl">
                Product photos to conversion-ready videos in under 2 minutes.
              </h1>
              <p className="mt-5 max-w-xl text-lg text-slate-600">
                NovaReel combines Nova 2 Lite, multimodal embeddings, and Nova 2 Sonic to generate polished 30-60 second product highlight videos.
              </p>
              <div className="mt-8 flex flex-wrap gap-3">
                <Link href="/app/dashboard" className="rounded-xl bg-ink px-5 py-3 text-sm font-semibold text-white hover:bg-slate-800">
                  Start generating
                </Link>
                <Link href="/features" className="rounded-xl border border-slate-300 px-5 py-3 text-sm font-semibold text-slate-700 hover:bg-slate-50">
                  Explore features
                </Link>
              </div>
            </div>

            <div className="surface overflow-hidden p-4">
              <div className="grid grid-cols-2 gap-3">
                <Image src="/product-1.svg" alt="Product example 1" width={320} height={220} className="h-44 w-full rounded-xl object-cover" priority />
                <Image src="/product-2.svg" alt="Product example 2" width={320} height={220} className="h-44 w-full rounded-xl object-cover" />
                <Image src="/product-3.svg" alt="Product example 3" width={640} height={240} className="col-span-2 h-36 w-full rounded-xl object-cover" />
              </div>
              <p className="mt-3 text-sm text-slate-600">Output: 1080p MP4, auto-subtitles, and voiceover optimized for ecommerce detail pages.</p>
            </div>
          </div>
        </section>

        <section className="container pb-8">
          <div className="surface grid gap-6 p-8 md:grid-cols-3">
            <article>
              <p className="text-xs font-semibold uppercase tracking-wide text-cedar">Multimodal script intelligence</p>
              <h2 className="mt-2 text-xl font-semibold">Context-aware storyboards</h2>
              <p className="mt-2 text-sm text-slate-600">Nova 2 Lite drafts ad-ready scripts and pairs each scene with the strongest product visual.</p>
            </article>
            <article>
              <p className="text-xs font-semibold uppercase tracking-wide text-cedar">Voice that sounds human</p>
              <h2 className="mt-2 text-xl font-semibold">Nova 2 Sonic narration</h2>
              <p className="mt-2 text-sm text-slate-600">Choose energetic, friendly, or professional voice profiles, with Polly as fallback for reliability.</p>
            </article>
            <article>
              <p className="text-xs font-semibold uppercase tracking-wide text-cedar">Built for conversion</p>
              <h2 className="mt-2 text-xl font-semibold">Seller-ready output</h2>
              <p className="mt-2 text-sm text-slate-600">Create clean 30-60 second videos tuned for product pages, ads, and social commerce channels.</p>
            </article>
          </div>
        </section>
      </main>

      <SiteFooter />
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify(structuredData) }} />
    </>
  );
}
