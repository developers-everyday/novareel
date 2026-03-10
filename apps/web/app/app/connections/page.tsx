'use client';

import { useAuth } from '@clerk/nextjs';
import { useEffect, useState } from 'react';
import {
  listSocialConnections,
  disconnectSocial,
  getSocialOAuthUrl,
} from '@/lib/api';
import type { SocialConnection } from '@/lib/contracts';

const PLATFORMS = [
  { id: 'youtube', label: 'YouTube', color: 'bg-red-600', hoverColor: 'hover:bg-red-700' },
] as const;

export default function ConnectionsPage() {
  const { getToken } = useAuth();

  const [connections, setConnections] = useState<SocialConnection[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    loadConnections().catch(() => undefined);
  }, []);

  async function loadConnections() {
    try {
      const token = await getToken();
      const items = await listSocialConnections(token);
      setConnections(items);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load connections');
    } finally {
      setLoading(false);
    }
  }

  async function onDisconnect(connectionId: string) {
    try {
      const token = await getToken();
      await disconnectSocial(connectionId, token);
      setConnections((prev) => prev.filter((c) => c.id !== connectionId));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Disconnect failed');
    }
  }

  function onConnect(platform: string) {
    window.location.href = getSocialOAuthUrl(platform);
  }

  if (loading) {
    return <p className="text-sm text-slate-600">Loading connections...</p>;
  }

  return (
    <div className="max-w-2xl space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-ink">Social Connections</h1>
        <p className="mt-1 text-sm text-slate-600">Connect your social media accounts to publish videos directly from NovaReel.</p>
      </div>

      {error ? <p className="rounded-lg bg-red-50 p-3 text-sm text-red-600">{error}</p> : null}

      <section className="surface p-6 space-y-4">
        {PLATFORMS.map((platform) => {
          const existing = connections.find((c) => c.platform === platform.id);

          return (
            <div key={platform.id} className="flex items-center justify-between rounded-lg border border-slate-200 p-4">
              <div>
                <p className="text-sm font-semibold text-ink">{platform.label}</p>
                {existing ? (
                  <p className="text-xs text-slate-500 mt-1">
                    Connected as <span className="font-medium">{existing.platform_username}</span>
                    &nbsp;&middot;&nbsp;
                    {new Date(existing.connected_at).toLocaleDateString()}
                  </p>
                ) : (
                  <p className="text-xs text-slate-500 mt-1">Not connected</p>
                )}
              </div>
              {existing ? (
                <button
                  type="button"
                  onClick={() => onDisconnect(existing.id).catch(() => undefined)}
                  className="rounded-lg border border-red-200 px-3 py-2 text-sm font-medium text-red-600 hover:bg-red-50"
                >
                  Disconnect
                </button>
              ) : (
                <button
                  type="button"
                  onClick={() => onConnect(platform.id)}
                  className={`rounded-lg ${platform.color} px-4 py-2 text-sm font-medium text-white ${platform.hoverColor}`}
                >
                  Connect {platform.label}
                </button>
              )}
            </div>
          );
        })}
      </section>

      {connections.length > 0 ? (
        <section className="surface p-6 space-y-3">
          <h2 className="text-lg font-semibold text-ink">All Connections</h2>
          <div className="divide-y divide-slate-100">
            {connections.map((conn) => (
              <div key={conn.id} className="flex items-center justify-between py-3">
                <div>
                  <p className="text-sm font-medium text-ink">{conn.platform_username}</p>
                  <p className="text-xs text-slate-500">
                    {conn.platform} &middot; expires {new Date(conn.token_expires_at).toLocaleDateString()}
                  </p>
                </div>
                <button
                  type="button"
                  onClick={() => onDisconnect(conn.id).catch(() => undefined)}
                  className="text-xs text-red-600 hover:text-red-800"
                >
                  Remove
                </button>
              </div>
            ))}
          </div>
        </section>
      ) : null}
    </div>
  );
}
