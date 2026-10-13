import { test, expect } from './fixtures';

test('a single experience carries number 1 on its bar and its card', async ({ page, api }) => {
	await page.goto('/class/class-1/plan');
	await expect(page.locator('.tl-num').first()).toHaveText('1');
	await expect(page.locator('.exp-num').first()).toContainText('1');
	expect(api.unexpected).toEqual([]);
});

test('experiences that share a week sit in one row, split at the day one ends', async ({
	page,
	api,
}) => {
	api.secondExperience = 'shared-week';
	await page.goto('/class/class-1/plan');
	const bars = page.locator('.tl-block');
	await expect(bars).toHaveCount(2);
	const first = await bars.nth(0).boundingBox();
	const second = await bars.nth(1).boundingBox();
	if (!first || !second) throw new Error('bars are not laid out');
	// One row: the same top edge.
	expect(Math.abs(first.y - second.y)).toBeLessThan(1);
	// Split, not overlapping, with a small gap at the boundary.
	const gap = second.x - (first.x + first.width);
	expect(gap).toBeGreaterThanOrEqual(0);
	expect(gap).toBeLessThan(8);
	// Widths follow the day counts: 5 days (Oct 5–9) and 7 days (Oct 10–16), each with a 3px inset.
	expect((first.width + 3) / 5).toBeCloseTo((second.width + 3) / 7, 0);
	expect(api.unexpected).toEqual([]);
});

test('adjacent experiences are separated and numbered in the order of their cards', async ({
	page,
	api,
}) => {
	api.secondExperience = 'adjacent';
	await page.goto('/class/class-1/plan');
	await expect(page.locator('.tl-num')).toHaveText(['1', '2']);
	await expect(page.locator('.card.exp').nth(1)).toContainText('Simulacros de pruebas');
	await expect(page.locator('.card.exp').nth(1).locator('.exp-num')).toContainText('2');
	const border = await page
		.locator('.tl-block')
		.first()
		.evaluate((el) => getComputedStyle(el).borderTopWidth);
	expect(border).toBe('2px');
	expect(api.unexpected).toEqual([]);
});
