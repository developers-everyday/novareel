'use client';

import { useAuth } from '@clerk/nextjs';
import { useEffect, useState } from 'react';
import {
  getBrandKit,
  updateBrandKit,
  listLibraryAssets,
  getLibraryAssetUploadUrl,
  deleteLibraryAsset,
  uploadAsset,
} from '@/lib/api';
import type { LibraryAsset } from '@/lib/contracts';

export default function BrandKitPage() {
  const { getToken } = useAuth();

  const [brandName, setBrandName] = useState('');
  const [primaryColor, setPrimaryColor] = useState('#1E40AF');
  const [secondaryColor, setSecondaryColor] = useState('#F59E0B');
  const [accentColor, setAccentColor] = useState('#10B981');
  const [logoAssetId, setLogoAssetId] = useState<string | null>(null);
  const [fontAssetId, setFontAssetId] = useState<string | null>(null);
  const [introClipAssetId, setIntroClipAssetId] = useState<string | null>(null);
  const [outroClipAssetId, setOutroClipAssetId] = useState<string | null>(null);

  const [assets, setAssets] = useState<LibraryAsset[]>([]);
  const [saving, setSaving] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    loadData().catch(() => undefined);
  }, []);

  async function loadData() {
    try {
      const token = await getToken();
      const [kit, libraryAssets] = await Promise.all([
        getBrandKit(token).catch(() => null),
        listLibraryAssets(token).catch(() => []),
      ]);
      if (kit) {
        setBrandName(kit.brand_name);
        setPrimaryColor(kit.primary_color);
        setSecondaryColor(kit.secondary_color);
        setAccentColor(kit.accent_color);
        setLogoAssetId(kit.logo_asset_id);
        setFontAssetId(kit.font_asset_id);
        setIntroClipAssetId(kit.intro_clip_asset_id);
        setOutroClipAssetId(kit.outro_clip_asset_id);
      }
      setAssets(libraryAssets);
      setLoaded(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load brand kit');
    }
  }

  async function onSave() {
    setSaving(true);
    setError(null);
    setSuccess(null);
    try {
      const token = await getToken();
      await updateBrandKit({
        brand_name: brandName,
        primary_color: primaryColor,
        secondary_color: secondaryColor,
        accent_color: accentColor,
        logo_asset_id: logoAssetId,
        font_asset_id: fontAssetId,
        intro_clip_asset_id: introClipAssetId,
        outro_clip_asset_id: outroClipAssetId,
      }, token);
      setSuccess('Brand kit saved successfully.');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to save brand kit');
    } finally {
      setSaving(false);
    }
  }

  async function onUploadAsset(file: File, assetType: LibraryAsset['asset_type']) {
    setUploading(true);
    setError(null);
    try {
      const token = await getToken();
      const resp = await getLibraryAssetUploadUrl({
        filename: file.name,
        asset_type: assetType,
        content_type: file.type || 'application/octet-stream',
        file_size: file.size,
      }, token);
      await uploadAsset(resp.upload_url, file, resp.headers, token);

      // Refresh asset list
      const updatedAssets = await listLibraryAssets(token);
      setAssets(updatedAssets);

      // Auto-assign to brand kit slot
      if (assetType === 'logo') setLogoAssetId(resp.asset_id);
      else if (assetType === 'font') setFontAssetId(resp.asset_id);
      else if (assetType === 'intro_clip') setIntroClipAssetId(resp.asset_id);
      else if (assetType === 'outro_clip') setOutroClipAssetId(resp.asset_id);

      setSuccess(`Uploaded ${file.name} as ${assetType}.`);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Upload failed');
    } finally {
      setUploading(false);
    }
  }

  async function onDeleteAsset(assetId: string) {
    try {
      const token = await getToken();
      await deleteLibraryAsset(assetId, token);
      setAssets((prev) => prev.filter((a) => a.id !== assetId));
      // Clear brand kit references
      if (logoAssetId === assetId) setLogoAssetId(null);
      if (fontAssetId === assetId) setFontAssetId(null);
      if (introClipAssetId === assetId) setIntroClipAssetId(null);
      if (outroClipAssetId === assetId) setOutroClipAssetId(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Delete failed');
    }
  }

  function getAssetFilename(assetId: string | null): string {
    if (!assetId) return 'None';
    const asset = assets.find((a) => a.id === assetId);
    return asset ? asset.filename : assetId.slice(0, 8);
  }

  if (!loaded) {
    return <p className="text-sm text-slate-600">Loading brand kit...</p>;
  }

  return (
    <div className="max-w-3xl space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-ink">Brand Kit</h1>
        <p className="mt-1 text-sm text-slate-600">Configure your brand identity. Logo, fonts, colors, and intro/outro clips will be applied to all generated videos.</p>
      </div>

      {error ? <p className="rounded-lg bg-red-50 p-3 text-sm text-red-600">{error}</p> : null}
      {success ? <p className="rounded-lg bg-green-50 p-3 text-sm text-green-600">{success}</p> : null}

      <section className="surface p-6 space-y-5">
        <h2 className="text-lg font-semibold text-ink">Brand Identity</h2>

        <label className="block text-sm font-medium text-slate-700">
          Brand name
          <input
            className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2"
            value={brandName}
            onChange={(e) => setBrandName(e.target.value)}
            placeholder="My Brand"
          />
        </label>

        <div className="grid gap-4 md:grid-cols-3">
          <label className="block text-sm font-medium text-slate-700">
            Primary color
            <div className="mt-1 flex items-center gap-2">
              <input
                type="color"
                value={primaryColor}
                onChange={(e) => setPrimaryColor(e.target.value)}
                className="h-10 w-10 cursor-pointer rounded border border-slate-300"
              />
              <input
                className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                value={primaryColor}
                onChange={(e) => setPrimaryColor(e.target.value)}
              />
            </div>
          </label>

          <label className="block text-sm font-medium text-slate-700">
            Secondary color
            <div className="mt-1 flex items-center gap-2">
              <input
                type="color"
                value={secondaryColor}
                onChange={(e) => setSecondaryColor(e.target.value)}
                className="h-10 w-10 cursor-pointer rounded border border-slate-300"
              />
              <input
                className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                value={secondaryColor}
                onChange={(e) => setSecondaryColor(e.target.value)}
              />
            </div>
          </label>

          <label className="block text-sm font-medium text-slate-700">
            Accent color
            <div className="mt-1 flex items-center gap-2">
              <input
                type="color"
                value={accentColor}
                onChange={(e) => setAccentColor(e.target.value)}
                className="h-10 w-10 cursor-pointer rounded border border-slate-300"
              />
              <input
                className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                value={accentColor}
                onChange={(e) => setAccentColor(e.target.value)}
              />
            </div>
          </label>
        </div>

        <div className="flex items-center gap-3">
          <div className="h-8 w-8 rounded" style={{ backgroundColor: primaryColor }} />
          <div className="h-8 w-8 rounded" style={{ backgroundColor: secondaryColor }} />
          <div className="h-8 w-8 rounded" style={{ backgroundColor: accentColor }} />
          <span className="text-xs text-slate-500">Color preview</span>
        </div>
      </section>

      <section className="surface p-6 space-y-5">
        <h2 className="text-lg font-semibold text-ink">Brand Assets</h2>

        <div className="grid gap-4 md:grid-cols-2">
          <div>
            <p className="text-sm font-medium text-slate-700">Logo</p>
            <p className="text-xs text-slate-500 mt-1">{getAssetFilename(logoAssetId)}</p>
            <label className="mt-2 inline-flex cursor-pointer items-center gap-2 rounded-lg border border-slate-300 px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50">
              Upload logo
              <input type="file" accept="image/*" className="hidden" disabled={uploading}
                onChange={(e) => { if (e.target.files?.[0]) onUploadAsset(e.target.files[0], 'logo'); }} />
            </label>
          </div>

          <div>
            <p className="text-sm font-medium text-slate-700">Custom font</p>
            <p className="text-xs text-slate-500 mt-1">{getAssetFilename(fontAssetId)}</p>
            <label className="mt-2 inline-flex cursor-pointer items-center gap-2 rounded-lg border border-slate-300 px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50">
              Upload font
              <input type="file" accept=".ttf,.otf" className="hidden" disabled={uploading}
                onChange={(e) => { if (e.target.files?.[0]) onUploadAsset(e.target.files[0], 'font'); }} />
            </label>
          </div>

          <div>
            <p className="text-sm font-medium text-slate-700">Intro clip</p>
            <p className="text-xs text-slate-500 mt-1">{getAssetFilename(introClipAssetId)}</p>
            <label className="mt-2 inline-flex cursor-pointer items-center gap-2 rounded-lg border border-slate-300 px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50">
              Upload intro
              <input type="file" accept="video/mp4" className="hidden" disabled={uploading}
                onChange={(e) => { if (e.target.files?.[0]) onUploadAsset(e.target.files[0], 'intro_clip'); }} />
            </label>
          </div>

          <div>
            <p className="text-sm font-medium text-slate-700">Outro clip</p>
            <p className="text-xs text-slate-500 mt-1">{getAssetFilename(outroClipAssetId)}</p>
            <label className="mt-2 inline-flex cursor-pointer items-center gap-2 rounded-lg border border-slate-300 px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50">
              Upload outro
              <input type="file" accept="video/mp4" className="hidden" disabled={uploading}
                onChange={(e) => { if (e.target.files?.[0]) onUploadAsset(e.target.files[0], 'outro_clip'); }} />
            </label>
          </div>
        </div>

        <button
          type="button"
          disabled={saving}
          onClick={() => onSave().catch(() => undefined)}
          className="rounded-lg bg-ink px-6 py-3 font-medium text-white transition hover:bg-slate-800 disabled:opacity-60"
        >
          {saving ? 'Saving...' : 'Save Brand Kit'}
        </button>
      </section>

      <section className="surface p-6 space-y-4">
        <h2 className="text-lg font-semibold text-ink">Asset Library</h2>
        <p className="text-sm text-slate-600">All uploaded assets. Delete items you no longer need.</p>

        {assets.length === 0 ? (
          <p className="text-sm text-slate-500">No assets uploaded yet.</p>
        ) : (
          <div className="divide-y divide-slate-100">
            {assets.map((asset) => (
              <div key={asset.id} className="flex items-center justify-between py-3">
                <div>
                  <p className="text-sm font-medium text-ink">{asset.filename}</p>
                  <p className="text-xs text-slate-500">
                    {asset.asset_type} &middot; {(asset.file_size / 1024).toFixed(0)} KB &middot; {new Date(asset.created_at).toLocaleDateString()}
                  </p>
                </div>
                <button
                  type="button"
                  onClick={() => onDeleteAsset(asset.id).catch(() => undefined)}
                  className="text-xs text-red-600 hover:text-red-800"
                >
                  Delete
                </button>
              </div>
            ))}
          </div>
        )}

        <label className="inline-flex cursor-pointer items-center gap-2 rounded-lg border border-slate-300 px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50">
          Upload music or image asset
          <input type="file" accept="image/*,audio/*" className="hidden" disabled={uploading}
            onChange={(e) => {
              if (e.target.files?.[0]) {
                const f = e.target.files[0];
                const type = f.type.startsWith('audio/') ? 'music' : 'image';
                onUploadAsset(f, type);
              }
            }} />
        </label>
      </section>
    </div>
  );
}
