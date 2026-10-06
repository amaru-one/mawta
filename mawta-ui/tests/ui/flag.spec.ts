import { test, expect } from './fixtures';
test('disabled planning redirects direct links to the class panel', async ({ page, api }) => {
	await page.goto('/class/class-1/plan/experience-1/criteria');
	await expect(page).toHaveURL('/class/class-1');
	await expect(page.getByRole('link', { name: /Plan del trimestre/ })).toHaveCount(0);
	expect(api.unexpected).toEqual([]);
});
