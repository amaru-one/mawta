import { test, expect, planningBase } from './fixtures';

const criteriaHref = `${planningBase}/criteria`;

test('Continuar with an unreviewed proposal asks first; "Revisar" stays, "Continuar de todos modos" moves on', async ({
	page,
	api,
}) => {
	await page.goto(criteriaHref);
	await page.getByRole('button', { name: 'Continuar con las evidencias' }).click();
	const dialog = page.getByRole('dialog');
	await expect(dialog).toContainText('Queda 1 propuesta sin revisar');
	await dialog.getByRole('button', { name: 'Revisar', exact: true }).click();
	await expect(page.getByRole('dialog')).toHaveCount(0);
	await expect(page).toHaveURL(new RegExp(`${criteriaHref}$`));

	await page.getByRole('button', { name: 'Continuar con las evidencias' }).click();
	await page.getByRole('button', { name: 'Continuar de todos modos' }).click();
	await expect(page).toHaveURL(new RegExp(`${planningBase}/evidences`));
	expect(api.unexpected).toEqual([]);
});

test('"Aceptar todas" reports the one failure, and a retry accepts it', async ({ page, api }) => {
	const [first] = api.experience.criteria ?? [];
	if (!first) throw new Error('seed has no criterio');
	api.experience.criteria?.push({ ...first, id: 'criterion-2', description: 'Segundo criterio.' });
	api.failures.add('/criteria/criterion-2/accept');
	await page.goto(criteriaHref);
	await page.getByRole('button', { name: 'Aceptar todas (2)', exact: true }).click();
	await expect(page.getByRole('alert')).toContainText('No se aceptaron 1 de 2 criterios');

	api.failures.delete('/criteria/criterion-2/accept');
	await page.getByRole('button', { name: 'Reintentar', exact: true }).click();
	await expect(page.getByRole('button', { name: /Aceptar todas/ })).toHaveCount(0);
	expect(api.unexpected).toEqual([]);
});

test('removing a criterio offers "Deshacer" that brings it back', async ({ page, api }) => {
	const description = 'Explica cómo calcula el cambio de una compra.';
	await page.goto(criteriaHref);
	await page.getByRole('button', { name: 'Quitar', exact: true }).first().click();
	await expect(page.getByText('Criterio quitado')).toBeVisible();
	await expect(page.getByText(description, { exact: true })).toHaveCount(0);
	await page.getByRole('button', { name: 'Deshacer', exact: true }).click();
	await expect(page.getByText(description, { exact: true })).toBeVisible();
	expect(api.unexpected).toEqual([]);
});

test('a competency with fewer than two evidences in the term is named on the summary, with a link', async ({
	page,
	api,
}) => {
	await page.goto(`${planningBase}/summary`);
	const notice = page.getByRole('link', { name: /Mawta necesita al menos 2/ });
	await expect(notice).toContainText('Resuelve problemas de cantidad');
	await expect(notice).toContainText('1 evidencia en el trimestre');
	await expect(notice).toHaveAttribute('href', /\/evidences\?from=summary$/);
	expect(api.unexpected).toEqual([]);
});

test('the summary links each pending kind to the step that owns it', async ({ page, api }) => {
	await page.goto(`${planningBase}/summary`);
	await expect(page.getByRole('link', { name: /en evidencias/ })).toHaveAttribute(
		'href',
		/\/evidences\?from=summary$/
	);
	await expect(page.getByRole('link', { name: /en criterios/ })).toHaveAttribute(
		'href',
		/\/criteria\?from=summary$/
	);
	expect(api.unexpected).toEqual([]);
});

test('sessions "Volver" still goes back to evidences', async ({ page, api }) => {
	await page.goto(`${planningBase}/sessions`);
	await expect(page.getByRole('link', { name: 'Volver', exact: true })).toHaveAttribute(
		'href',
		/\/evidences$/
	);
	expect(api.unexpected).toEqual([]);
});
