import type { Metadata } from 'next';
import { ClerkProvider } from '@clerk/nextjs';
import './globals.css';

const baseUrl = process.env.NEXT_PUBLIC_APP_URL ?? 'http://localhost:3000';

export const metadata: Metadata = {
  metadataBase: new URL(baseUrl),
  title: {
    default: 'NovaReel | AI Product Video Generator',
    template: '%s | NovaReel'
  },
  description:
    'Create 30-60 second product videos from images and product details using Amazon Nova multimodal AI.',
  openGraph: {
    title: 'NovaReel',
    description: 'AI-generated product videos for Amazon sellers and ecommerce brands.',
    url: baseUrl,
    siteName: 'NovaReel',
    type: 'website'
  },
  twitter: {
    card: 'summary_large_image',
    title: 'NovaReel',
    description: 'Create product videos in minutes with Amazon Nova.'
  },
  alternates: {
    canonical: '/'
  }
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <ClerkProvider>
      <html lang="en">
        <body>{children}</body>
      </html>
    </ClerkProvider>
  );
}
