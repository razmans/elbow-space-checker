import { test, expect } from '@playwright/test';

// Exercise the real HTTP/SSE service; no mocked network responses.
test('three independent simulated coaches update live and match the platform layout', async ({ page, request }) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  let navigationCount = 0;
  page.on('framenavigated', frame => { if (frame === page.mainFrame()) navigationCount++; });
  await page.goto('/');
  await expect(page.locator('.coach-card .source-tag')).toHaveCount(3);
  const first = page.getByTestId('coach-coach-01');
  await expect(first.getByTestId('occupancy')).toHaveText(/\d+%/);
  const initial = await first.getAttribute('data-observation-id');
  await expect(first).not.toHaveAttribute('data-observation-id', initial!);
  await expect(page.getByText('Live connection', { exact: true })).toBeVisible();
  await expect(page.getByTestId('coach-coach-02')).toHaveAttribute('data-status', 'yellow');
  await expect(page.getByTestId('coach-coach-03')).toHaveAttribute('data-status', 'red');
  await expect(page.getByTestId('coach-coach-02')).toContainText('/ 120 capacity');
  await expect(page.getByTestId('coach-coach-03')).toContainText('/ 80 capacity');
  const layout = page.getByRole('region', { name: 'Configured platform layout' });
  await expect(layout.locator('.layout-name')).toHaveText(['Coach 01', 'Coach 02', 'Coach 03']);
  await expect(layout.locator('.layout-zone')).toHaveText(['Zone A', 'Zone B', 'Zone C']);
  await expect(layout).toContainText('Travel direction →');
  const history = await (await request.get('/api/observations')).json();
  expect(new Set(history.map((row: { coach_id: string }) => row.coach_id)).size).toBe(3);
  expect(navigationCount).toBe(1);
  expect(errors).toEqual([]);
  await page.screenshot({ path: 'test-results/desktop.png', fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(first.getByTestId('occupancy')).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: 'test-results/mobile.png', fullPage: true });
});

test('offline readings expire locally and reconnect retrieves every coach without refreshing', async ({ page, context }) => {
  let navigations = 0;
  page.on('framenavigated', frame => { if (frame === page.mainFrame()) navigations++; });
  await page.goto('/');
  const cards = page.locator('.coach-card');
  await expect(cards).toHaveCount(3);
  await expect(page.getByText('Live connection', { exact: true })).toBeVisible();
  const previousId = Number(await cards.first().getAttribute('data-observation-id'));
  await context.setOffline(true);
  for (const card of await cards.all()) {
    await expect(card).toHaveAttribute('data-status', 'unknown', { timeout: 6000 });
    await expect(card.getByTestId('occupancy')).toHaveText('—');
    await expect(card).toContainText('Stale');
  }
  await expect(page.locator('.layout-coach.unknown')).toHaveCount(3);
  await page.screenshot({ path: 'test-results/stale.png', fullPage: true });
  await context.setOffline(false);
  await expect(page.getByText('Live connection', { exact: true })).toBeVisible({ timeout: 10000 });
  await expect.poll(async () => Number(await cards.first().getAttribute('data-observation-id'))).toBeGreaterThan(previousId);
  await expect(page.locator('.coach-card.unknown')).toHaveCount(0);
  expect(navigations).toBe(1);
});

test('history pages and coach filter remain separate from live readings', async ({ page }) => {
  await page.goto('/');
  const history = page.getByRole('region', { name: 'Observation history', exact: true });
  await expect(history.getByRole('button', { name: 'Older', exact: true })).toBeEnabled({ timeout: 15000 });
  const firstId = await history.locator('tbody tr').first().getAttribute('data-testid');
  await history.getByRole('button', { name: 'Older', exact: true }).click();
  await expect(history.getByText('Page 2', { exact: true })).toBeVisible();
  await expect(history.locator('tbody tr').first()).not.toHaveAttribute('data-testid', firstId!);
  await history.getByRole('button', { name: 'Latest', exact: true }).click();
  await expect(history.getByText('Page 1', { exact: true })).toBeVisible();
  await history.getByLabel('Coach', { exact: true }).selectOption('coach-02');
  await expect(history.locator('tbody tr').first().locator('td').first()).toContainText('Coach 02');
  const names = await history.locator('tbody td:first-child strong').allTextContents();
  expect(names.length).toBeGreaterThan(0);
  expect(names.every(name => name === 'Coach 02')).toBe(true);
  await expect(history.locator('tbody tr').first()).toContainText('Simulated data');
  await page.screenshot({ path: 'test-results/history-desktop.png', fullPage: true });
});
