import { test, expect } from './fixtures';

test('a single experience carries number 1 on its bar and its card', async ({ page, api }) => {
	await page.goto('/class/class-1/plan');
	await expect(page.locator('.tl-num').first()).toHaveText('1');
	await expect(page.locator('.exp-num').first()).toContainText('1');
	expect(api.unexpected).toEqual([]);
});

test('adjacent experiences are separated and numbered in the order of their cards', async ({
	page,
	api,
}) => {
	api.secondExperience = true;
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
