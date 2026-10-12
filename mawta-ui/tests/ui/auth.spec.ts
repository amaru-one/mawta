import type { Page } from '@playwright/test';
import { test, expect } from './fixtures';

async function signIn(page: Page) {
	await page.getByLabel('Usuario', { exact: true }).fill('teacher');
	await page.getByLabel('Contraseña', { exact: true }).fill('password');
	await page.getByRole('button', { name: 'Ingresar', exact: true }).click();
}

test('an expired session returns to login and then to the page that was open', async ({
	page,
	api,
}) => {
	api.meStatus = 401;
	await page.goto('/class/class-1/students');
	await expect(page).toHaveURL(/\/login\?next=%2Fclass%2Fclass-1%2Fstudents$/);
	await signIn(page);
	await expect(page).toHaveURL(/\/class\/class-1\/students$/);
});

test('a failed session check offers a retry instead of signing the teacher out', async ({
	page,
	api,
}) => {
	api.meStatus = 500;
	await page.goto('/class/class-1');
	await expect(page.getByRole('alert')).toContainText('No pudimos conectar con Mawta');
	await expect(page).toHaveURL(/\/class\/class-1$/);
	api.meStatus = 200;
	await page.getByRole('button', { name: 'Reintentar', exact: true }).click();
	await expect(page).toHaveTitle('Matemática — Panel');
});

for (const next of ['https://evil.test/', '//evil.test/', '/login']) {
	test(`login ignores an unsafe next target (${next})`, async ({ page, api }) => {
		await page.goto(`/login?next=${encodeURIComponent(next)}`);
		await signIn(page);
		await expect(page).toHaveURL('/');
	});
}
