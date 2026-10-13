import { test, expect, studentRoute } from './fixtures';

const conclusionsPath = '/classes/class-1/students/student-1/conclusions';
const levelPath = '/classes/class-1/students/student-1/competency-levels';

test('leaving with an unsaved conclusion asks once, and "Seguir editando" keeps the draft', async ({
	page,
	api,
}) => {
	await page.goto(studentRoute);
	await page.getByLabel('Conclusión descriptiva', { exact: true }).fill('Explica bien el cambio.');
	await page.getByRole('link', { name: 'Volver', exact: true }).click();
	const dialog = page.getByRole('alertdialog');
	await expect(dialog).toContainText('¿Salir sin guardar?');
	await dialog.getByRole('button', { name: 'Seguir editando', exact: true }).click();
	await expect(dialog).toBeHidden();
	await expect(page.getByLabel('Conclusión descriptiva', { exact: true })).toHaveValue(
		'Explica bien el cambio.'
	);
	expect(api.unexpected).toEqual([]);
});

test('a failed conclusion save offers a retry that then saves', async ({ page, api }) => {
	api.failures.add(conclusionsPath);
	await page.goto(studentRoute);
	await page.getByLabel('Conclusión descriptiva', { exact: true }).fill('Explica bien el cambio.');
	await page.getByRole('button', { name: 'Guardar borrador', exact: true }).click();
	await expect(page.getByRole('alert').first()).toBeVisible();

	api.failures.delete(conclusionsPath);
	await page.getByRole('button', { name: 'Reintentar', exact: true }).click();
	await expect(page.getByText('Borrador guardado', { exact: true })).toBeVisible();
	expect(api.writes.some((w) => w.path === conclusionsPath)).toBe(true);
});

test('changing a level offers "Deshacer" that restores the previous one', async ({ page, api }) => {
	const [level] = api.levels;
	if (!level) throw new Error('seed has no competency level');
	level.level = 'B';
	await page.goto(studentRoute);
	await page
		.getByRole('group', { name: 'Nivel de logro' })
		.getByRole('radio', { name: 'AD · Destacado' })
		.check({ force: true });
	await expect(page.getByText('Nivel guardado', { exact: true })).toBeVisible();
	await page.getByRole('button', { name: 'Deshacer', exact: true }).click();
	await expect
		.poll(() => api.writes.filter((w) => w.path === levelPath).map((w) => w.body.level))
		.toEqual(['AD', 'B']);
	expect(api.unexpected).toEqual([]);
});
