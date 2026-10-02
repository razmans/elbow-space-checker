import { test, expect } from '@playwright/test';

test('real RTSP, local models, three coaches and persisted history form a complete demo', async ({ page, request }) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto('/');
  const live = page.getByTestId('coach-coach-01');
  await expect(live).toContainText('RTSP replay');
  await expect(live).toContainText('Live RTSP');
  await expect(live.getByTestId('occupancy')).toHaveText('0%', { timeout: 20000 });
  await expect(page.getByTestId('coach-coach-02')).toContainText('Simulated data');
  await expect(page.getByTestId('coach-coach-03')).toContainText('Simulated data');
  await expect.poll(async () => {
    const rows = await (await request.get('/api/observations')).json();
    return rows.some((row: { source: string; verification: { status: string } }) => row.source === 'rtsp' && ['verified', 'unavailable'].includes(row.verification.status));
  }, { timeout: 90000 }).toBe(true);
  const rows = await (await request.get('/api/history?coach_id=coach-01')).json();
  const checked = rows.items.find((row: { verification: { status: string } }) => ['verified', 'unavailable'].includes(row.verification.status));
  expect(checked.detector).toBe('mobilenet-ssd-voc');
  expect(checked.verification.model).toBe('elbow-verifier');
  expect(checked.sample_counts).toHaveLength(3);
  await page.getByLabel('Coach', { exact: true }).selectOption('coach-01');
  await expect(page.getByTestId(`history-${checked.id}`)).toBeVisible();
  await page.screenshot({ path: 'test-results/complete-demo-desktop.png', fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: 'test-results/complete-demo-mobile.png', fullPage: true });
  expect(errors).toEqual([]);
});
