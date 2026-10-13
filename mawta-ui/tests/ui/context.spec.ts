import { test, expect, planningBase } from './fixtures';

const newPlan = '/class/class-1/plan/new';

test('the event field stays hidden until the teacher asks for it', async ({ page, api }) => {
	await page.goto(newPlan);
	await expect(page.getByLabel('Evento o contexto', { exact: true })).toHaveCount(0);
	await page.getByRole('button', { name: '+ Agregar un evento o contexto (opcional)' }).click();
	await expect(page.getByLabel('Evento o contexto', { exact: true })).toBeVisible();
	expect(api.unexpected).toEqual([]);
});

test('a filled event is saved with the experience', async ({ page, api }) => {
	await page.goto(newPlan);
	await page
		.getByLabel('Tu idea', { exact: true })
		.fill('Organizar una tiendita para practicar vueltos');
	await page.getByRole('button', { name: '+ Agregar un evento o contexto (opcional)' }).click();
	await page.getByLabel('Evento o contexto', { exact: true }).fill('Feria del aula de compras');
	await page.getByRole('button', { name: 'Escribirlo yo', exact: true }).click();
	await page.getByLabel('Nombre', { exact: true }).fill('Tiendita escolar');
	await page.getByRole('button', { name: 'Guardar borrador', exact: true }).click();
	await expect(page).toHaveURL(/\/criteria$/);
	const write = api.writes.find((w) => w.path === '/classes/class-1/experiences');
	expect(write?.body.context_text).toBe('Feria del aula de compras');
});

test('without an event the experience is saved with no context', async ({ page, api }) => {
	await page.goto(newPlan);
	await page
		.getByLabel('Tu idea', { exact: true })
		.fill('Organizar una tiendita para practicar vueltos');
	await page.getByRole('button', { name: 'Escribirlo yo', exact: true }).click();
	await page.getByLabel('Nombre', { exact: true }).fill('Tiendita escolar');
	await page.getByRole('button', { name: 'Guardar borrador', exact: true }).click();
	await expect(page).toHaveURL(/\/criteria$/);
	const write = api.writes.find((w) => w.path === '/classes/class-1/experiences');
	expect(write?.body.context_text ?? null).toBeNull();
});

test('the generation request carries the event only when one was written', async ({
	page,
	api,
}) => {
	await page.goto(newPlan);
	await page
		.getByLabel('Tu idea', { exact: true })
		.fill('Organizar una tiendita para practicar vueltos');
	await page.getByRole('button', { name: '+ Agregar un evento o contexto (opcional)' }).click();
	await page.getByLabel('Evento o contexto', { exact: true }).fill('Feria del aula de compras');
	await page.getByRole('button', { name: '✦ Generar con Mawta' }).click();
	await expect
		.poll(() => api.writes.find((w) => w.path.endsWith('/experience-proposals'))?.body.context_text)
		.toBe('Feria del aula de compras');
});

test('the summary shows the event the teacher gave', async ({ page, api }) => {
	await page.goto(`${planningBase}/summary`);
	await expect(page.getByText('Evento o contexto: Feria del aula de compras')).toBeVisible();
	expect(api.unexpected).toEqual([]);
});
