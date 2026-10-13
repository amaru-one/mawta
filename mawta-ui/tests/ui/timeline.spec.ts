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
	// Both run three class days (Oct 5, 7, 9 and Oct 12, 14, 16), so their bars match in width.
	expect(Math.abs(first.width - second.width)).toBeLessThan(1);
	expect(api.unexpected).toEqual([]);
});

test('a feriado on a class day is a dot under the line; a feriado on a day without class is not drawn', async ({
	page,
	api,
}) => {
	await page.goto('/class/class-1/plan');
	// Oct 21 is a Wednesday class: one dot. Oct 8 is a Thursday: no dot.
	const dots = page.locator('.tl-dot');
	await expect(dots).toHaveCount(1);
	await expect(page.locator('.tl-band')).toHaveCount(0);
	const bar = await page.locator('.tl-block').first().boundingBox();
	const dot = await dots.boundingBox();
	if (!bar || !dot) throw new Error('timeline is not laid out');
	// The dot sits below the line of bars, never over an experience.
	expect(dot.y).toBeGreaterThanOrEqual(bar.y + bar.height);
	expect(api.unexpected).toEqual([]);
});

test('a vacation covering a whole week of classes marks the week, with its name', async ({
	page,
	api,
}) => {
	api.vacationWeek = true;
	await page.goto('/class/class-1/plan');
	const vacation = page.locator('.tl-band', { hasText: 'vacaciones' });
	await expect(vacation).toHaveCount(1);
	const track = await page.locator('.tl-track').boundingBox();
	const box = await vacation.boundingBox();
	if (!track || !box) throw new Error('timeline is not laid out');
	expect(Math.abs(box.width + 3 - track.width / 12)).toBeLessThan(1.5);
	// The band is its own row under the bars, so it never covers an experience.
	const bar = await page.locator('.tl-block').first().boundingBox();
	if (!bar) throw new Error('bar is not laid out');
	expect(box.y).toBeGreaterThanOrEqual(bar.y + bar.height);
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
