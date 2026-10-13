import { test, expect } from './fixtures';

const newPlan = '/class/class-1/plan/new';

async function openReview(page: import('@playwright/test').Page) {
	await page.goto(newPlan);
	await page
		.getByLabel('Tu idea', { exact: true })
		.fill('Organizar una tiendita para practicar vueltos');
	await page.getByRole('button', { name: 'Escribirlo yo', exact: true }).click();
	await page.getByLabel('Nombre', { exact: true }).fill('Tiendita escolar');
	await expect(
		page.getByRole('button', { name: 'lunes 12 de octubre de 2026, inicio' })
	).toBeVisible();
}

test('the calendar cannot move before the term start or after its end', async ({ page, api }) => {
	await openReview(page);
	await expect(page.getByRole('button', { name: 'Mes anterior' })).toBeDisabled();
	for (let i = 0; i < 2; i++) await page.getByRole('button', { name: 'Mes siguiente' }).click();
	await expect(page.getByText('diciembre 2026', { exact: true })).toBeVisible();
	await expect(page.getByRole('button', { name: 'Mes siguiente' })).toBeDisabled();
	expect(api.unexpected).toEqual([]);
});

test('holidays and days of another experience are shown but cannot be picked', async ({
	page,
	api,
}) => {
	await openReview(page);
	const holiday = page.getByRole('button', { name: 'miércoles 21 de octubre de 2026, feriado' });
	await expect(holiday).toHaveAttribute('aria-disabled', 'true');
	const busy = page.getByRole('button', {
		name: 'lunes 5 de octubre de 2026, ocupado por otra experiencia',
	});
	await expect(busy).toHaveAttribute('aria-disabled', 'true');
});

test('a holiday inside the range is allowed but cannot be the end', async ({ page, api }) => {
	await openReview(page);
	await page.getByRole('button', { name: 'viernes 23 de octubre de 2026, disponible' }).click();
	await expect(
		page.getByRole('button', { name: 'viernes 23 de octubre de 2026, fin' })
	).toBeVisible();
	// A disabled day refuses the tap: the forced click proves nothing changes.
	await page
		.getByRole('button', { name: 'miércoles 21 de octubre de 2026, feriado' })
		.click({ force: true });
	await expect(
		page.getByRole('button', { name: 'viernes 23 de octubre de 2026, fin' })
	).toBeVisible();
});

test('a new start is chosen with the Inicio chip, suggests an end, and a later day changes it', async ({
	page,
	api,
}) => {
	await openReview(page);
	await page.getByRole('button', { name: /^Inicio/ }).click();
	await page.getByRole('button', { name: 'miércoles 14 de octubre de 2026, disponible' }).click();
	await expect(
		page.getByRole('button', { name: 'miércoles 14 de octubre de 2026, inicio' })
	).toBeVisible();
	await expect(
		page.getByRole('button', { name: 'viernes 30 de octubre de 2026, fin' })
	).toBeVisible();
	await page.getByRole('button', { name: 'lunes 19 de octubre de 2026, disponible' }).click();
	await expect(
		page.getByRole('button', { name: 'lunes 19 de octubre de 2026, fin' })
	).toBeVisible();
});

test('arrow keys move focus by day and week', async ({ page, api }) => {
	await openReview(page);
	await page.getByRole('button', { name: 'lunes 12 de octubre de 2026, inicio' }).focus();
	await page.keyboard.press('ArrowDown');
	await expect(
		page.getByRole('button', { name: 'lunes 19 de octubre de 2026, disponible' })
	).toBeFocused();
	await page.keyboard.press('ArrowRight');
	await expect(
		page.getByRole('button', { name: 'martes 20 de octubre de 2026, sin clase' })
	).toBeFocused();
});

test('the calendar fits a 320px screen with touch-sized days', async ({ page, api }) => {
	await page.setViewportSize({ width: 320, height: 800 });
	await openReview(page);
	expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(320);
	const day = page.getByRole('button', { name: 'lunes 12 de octubre de 2026, inicio' });
	const box = await day.boundingBox();
	expect(box?.height ?? 0).toBeGreaterThanOrEqual(44);
});
