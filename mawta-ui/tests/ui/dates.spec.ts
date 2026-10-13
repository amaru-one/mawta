import { test, expect, planningBase } from './fixtures';

test('home hour labels stay on one line', async ({ page, api }) => {
	await page.goto('/');
	const labels = page.locator('.hlabel');
	await expect(labels.first()).toBeVisible();
	const count = await labels.count();
	for (let i = 0; i < count; i++) {
		const box = await labels.nth(i).boundingBox();
		expect(box?.height ?? 0).toBeLessThan(20);
	}
	expect(api.unexpected).toEqual([]);
});

test('term strip weeks show the date each week opens on', async ({ page, api }) => {
	await page.goto(`${planningBase.replace('/plan/experience-1', '/plan')}`);
	await expect(page.locator('.tl-head b').first()).toHaveText(/^\d{1,2} \w{3}$/);
	expect(api.unexpected).toEqual([]);
});

test('date fields summarize the range with its year and week count', async ({ page, api }) => {
	await page.goto('/class/class-1/plan/new');
	await page.getByLabel('Tu idea', { exact: true }).fill('Organizar una feria del aula');
	await page.getByRole('button', { name: 'Escribirlo yo', exact: true }).click();
	await page.getByLabel('Nombre', { exact: true }).fill('Feria de compras');
	await expect(page.getByText(/\d+ semanas/)).toBeVisible();
	expect(api.unexpected).toEqual([]);
});
