import { test, expect } from './fixtures';

const newEvidence = '/class/class-1/evidence/new';

test('a dirty evidence form asks once before leaving, and stays put on "Seguir editando"', async ({
	page,
	api,
}) => {
	await page.goto(newEvidence);
	await page.getByLabel('Título', { exact: true }).fill('Práctica de compras');
	await page.getByRole('link', { name: 'Volver', exact: true }).click();
	const dialog = page.getByRole('alertdialog');
	await expect(dialog).toContainText('¿Salir sin guardar?');
	await dialog.getByRole('button', { name: 'Seguir editando', exact: true }).click();
	await expect(dialog).toBeHidden();
	await expect(page).toHaveURL(new RegExp(`${newEvidence}$`));
	await expect(page.getByLabel('Título', { exact: true })).toHaveValue('Práctica de compras');
});

test('"Descartar" leaves without a second prompt', async ({ page, api }) => {
	await page.goto(newEvidence);
	await page.getByLabel('Título', { exact: true }).fill('Práctica de compras');
	await page.getByRole('link', { name: 'Volver', exact: true }).click();
	const dialog = page.getByRole('alertdialog');
	await dialog.getByRole('button', { name: 'Descartar', exact: true }).click();
	await expect(page).toHaveURL(/\/class\/class-1$/);
	await expect(page.getByRole('alertdialog')).toHaveCount(0);
});

test('a clean form leaves without asking', async ({ page, api }) => {
	await page.goto(newEvidence);
	await page.getByRole('link', { name: 'Volver', exact: true }).click();
	await expect(page).toHaveURL(/\/class\/class-1$/);
	await expect(page.getByRole('alertdialog')).toHaveCount(0);
});

test('a successful save navigates without prompting', async ({ page, api }) => {
	await page.goto(newEvidence);
	await page.getByLabel('Título', { exact: true }).fill('Práctica de compras');
	await page.getByRole('checkbox').first().check();
	await page.getByRole('button', { name: 'Guardar evidencia', exact: true }).click();
	await expect(page).toHaveURL(/\/class\/class-1$/);
	await expect(page.getByRole('alertdialog')).toHaveCount(0);
});

test('reloading a dirty form raises exactly one native unload prompt', async ({ page, api }) => {
	await page.goto(newEvidence);
	await page.getByLabel('Título', { exact: true }).fill('Práctica de compras');
	let prompts = 0;
	page.on('dialog', (dialog) => {
		prompts += 1;
		void dialog.dismiss();
	});
	// The reload itself waits on the pending prompt, so don't await it.
	void page.reload({ waitUntil: 'commit' }).catch(() => {});
	await expect.poll(() => prompts).toBeGreaterThan(0);
	await page.waitForTimeout(500);
	expect(prompts).toBe(1);
});

// Spike: browser Back with a dirty form. Expected behaviour is one in-app prompt.
// If the framework cannot cancel popstate, this test documents the native-only fallback.
test('browser Back with a dirty form asks before leaving', async ({ page, api }) => {
	await page.goto('/class/class-1');
	await page.getByRole('link', { name: 'Añadir evidencia' }).click();
	await expect(page).toHaveURL(/\/class\/class-1\/evidence\/new/);
	await page.getByLabel('Título', { exact: true }).fill('Práctica de compras');
	await page.goBack();
	await expect(page.getByRole('alertdialog')).toContainText('¿Salir sin guardar?');
	await expect(page).toHaveURL(/\/class\/class-1\/evidence\/new/);
});
