import { test, expect, routeCases } from './fixtures';

// Interactive controls must meet the 44px touch minimum (iOS HIG).
const MIN_TARGET = 44;
const TARGETS =
	'.mw-icon-button, .mw-action, .mw-seg button, .mw-topbar__identity, a.mw-session__evidence';

for (const [url, , text] of routeCases) {
	test(`touch targets are at least ${MIN_TARGET}px on ${url}`, async ({ page, api }) => {
		await page.setViewportSize({ width: 390, height: 844 });
		await page.goto(url);
		await expect(page.getByText(text, { exact: false }).first()).toBeVisible();
		await expect(page.locator('.mw-loading')).toHaveCount(0);
		const small: string[] = [];
		for (const el of await page.locator(TARGETS).all()) {
			if (!(await el.isVisible())) continue;
			const box = await el.boundingBox();
			if (!box) continue;
			if (box.width < MIN_TARGET || box.height < MIN_TARGET) {
				const label = (await el.getAttribute('aria-label')) ?? (await el.textContent())?.trim();
				small.push(`${Math.round(box.width)}x${Math.round(box.height)} ${label ?? ''}`);
			}
		}
		expect(small).toEqual([]);
		expect(api.unexpected).toEqual([]);
	});
}
