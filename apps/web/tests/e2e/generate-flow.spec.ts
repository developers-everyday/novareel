import { expect, test } from '@playwright/test';

test.describe('NovaReel generation flow', () => {
  test('opens marketing pages and dashboard route', async ({ page }) => {
    await page.goto('/');
    await expect(page.getByRole('heading', { name: /Product photos to conversion-ready videos/i })).toBeVisible();

    await page.goto('/features');
    await expect(page.getByRole('heading', { name: /NovaReel Features/i })).toBeVisible();

    await page.goto('/pricing');
    await expect(page.getByRole('heading', { name: /Pricing/i })).toBeVisible();
  });
});
