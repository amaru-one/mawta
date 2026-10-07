import { test, expect, routeCases, studentRoute, gradesRoute, planningBase } from './fixtures';

for (const [url, title, text] of routeCases) {
	test(`screen ${url}`, async ({ page, api }, info) => {
		const errors: string[] = [];
		page.on('pageerror', (error) => errors.push(error.message));
		await page.goto(url);
		await expect(page).toHaveTitle(title);
		await expect(page.getByText(text, { exact: false }).first()).toBeVisible();
		await expect(page.locator('.mw-loading')).toHaveCount(0);
		for (const width of [320, 390, 480, 1280]) {
			await page.setViewportSize({ width, height: 844 });
			expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(
				width
			);
			const shell = await page.locator('.app-shell').boundingBox();
			expect(shell?.width).toBeLessThanOrEqual(480);
			expect(
				await page
					.locator('.mw-root')
					.evaluate((el) => getComputedStyle(el).getPropertyValue('--mw-accent').trim())
			).toBe('#4f46e5');
			await page.screenshot({ path: info.outputPath(`screen-${width}.png`), fullPage: true });
		}
		expect(errors).toEqual([]);
		expect(api.unexpected).toEqual([]);
	});
}

test('login errors stay visible, then a successful login opens home', async ({ page, api }) => {
	api.loginError = true;
	await page.goto('/login');
	await page.getByLabel('Usuario', { exact: true }).fill('teacher');
	await page.getByLabel('Contraseña', { exact: true }).fill('password');
	await page.getByRole('button', { name: 'Ingresar', exact: true }).click();
	await expect(page.getByText('Usuario o contraseña incorrectos.')).toBeVisible();
	api.loginError = false;
	await page.getByRole('button', { name: 'Ingresar', exact: true }).click();
	await expect(page).toHaveURL('/');
	expect(api.writes.filter((w) => w.path === '/auth/login')).toHaveLength(2);
});

test('native navigation preserves deep links, browser back, and modifier clicks', async ({
	page,
	context,
	api,
}) => {
	await page.goto('/class/class-1/students');
	await page.getByRole('link', { name: /Quispe, Ana/ }).click();
	await expect(page).toHaveURL(/students\/student-1/);
	await page.getByRole('link', { name: 'Volver', exact: true }).click();
	await expect(page).toHaveURL('/class/class-1/students');
	const popupPromise = context.waitForEvent('page');
	await page.getByRole('link', { name: /Quispe, Ana/ }).click({ modifiers: ['ControlOrMeta'] });
	const popup = await popupPromise;
	expect(popup.url()).toContain('students/student-1');
	await popup.close();
	expect(api.writes).toHaveLength(0);
});

test('notifications retain filters and mark-all behavior', async ({ page, api }) => {
	await page.goto('/notifications');
	await page.getByRole('button', { name: 'Marcar todas leídas' }).click();
	await expect(page.getByRole('button', { name: 'Marcar todas leídas' })).toHaveCount(0);
	expect(api.writes.some((w) => w.path === '/notifications/read-all')).toBe(true);
});

test('manual planning keeps optional situation and free class dates', async ({ page, api }) => {
	await page.goto('/class/class-1/plan/new');
	await page.getByLabel('Tu idea', { exact: true }).fill('Organizar una feria del aula');
	await page.getByRole('button', { name: 'Escribirlo yo', exact: true }).click();
	await page.getByLabel('Nombre', { exact: true }).fill('Feria de compras');
	await expect(page.getByLabel('Empieza', { exact: true })).toHaveValue('2026-10-12');
	await page.getByRole('button', { name: 'Guardar borrador', exact: true }).click();
	await expect(page).toHaveURL(/\/criteria$/);
	const write = api.writes.find((w) => w.path === '/classes/class-1/experiences');
	expect(write?.body).toMatchObject({
		title: 'Feria de compras',
		starts_on: '2026-10-12',
		competency_ids: ['comp-1'],
	});
	expect(write?.body.situation_text ?? '').toBe('');
});

test('unavailable generation offers manual planning without losing the idea', async ({
	page,
	api,
}) => {
	api.unavailable = true;
	await page.goto('/class/class-1/plan/new');
	await page.getByLabel('Tu idea', { exact: true }).fill('Una feria de matemáticas');
	await page.getByRole('button', { name: 'Generar con Mawta' }).click();
	await expect(
		page.getByText('Mawta no puede generar en este momento. Puedes escribirlo a mano.')
	).toBeVisible();
	await expect(page.getByRole('button', { name: 'Generar con Mawta' })).toHaveCount(0);
	await page.getByRole('button', { name: 'Escribir la experiencia' }).click();
	await expect(page.getByText(/Una feria de matemáticas/)).toBeVisible();
});

test('generated proposal preserves the returned dates for review', async ({ page, api }) => {
	await page.goto('/class/class-1/plan/new');
	await page.getByLabel('Tu idea', { exact: true }).fill('Una feria');
	await page.getByRole('button', { name: 'Generar con Mawta' }).click();
	await expect(page.getByLabel('Nombre', { exact: true })).toHaveValue('La feria del aula');
	await expect(page.getByLabel('Empieza', { exact: true })).toHaveValue('2026-10-12');
	await expect(page.getByLabel('Termina', { exact: true })).toHaveValue('2026-10-16');
	expect(api.writes.some((w) => w.path.endsWith('/experience-proposals'))).toBe(true);
});

test('criteria accept and edit preserve capability associations', async ({ page, api }) => {
	await page.goto(`${planningBase}/criteria`);
	await page.getByRole('button', { name: 'Aceptar', exact: true }).click();
	await expect(page.getByRole('button', { name: 'Aceptar', exact: true })).toHaveCount(0);
	await page.getByRole('button', { name: 'Editar', exact: true }).click();
	await page
		.getByLabel('Criterio', { exact: true })
		.fill('Explica y verifica el cambio de una compra.');
	await page.getByRole('button', { name: 'Guardar', exact: true }).click();
	await expect(page.getByText('Explica y verifica el cambio de una compra.')).toBeVisible();
	expect(
		api.writes.find((w) => w.method === 'PUT' && w.path === '/criteria/criterion-1')?.body
	).toMatchObject({ capability_ids: ['cap-1'], performance_id: 'performance-1' });
});

test('evidence deletion can be undone throughout the seven-second toast', async ({ page, api }) => {
	await page.goto(`${planningBase}/evidences`);
	await page.getByRole('button', { name: 'Quitar', exact: true }).click();
	await expect(page.getByText('Lista de precios', { exact: true })).toHaveCount(0);
	await page.waitForTimeout(2200);
	await page.getByRole('button', { name: 'Deshacer', exact: true }).click();
	await expect(page.getByText('Lista de precios', { exact: true })).toBeVisible();
	expect(
		api.writes.find((w) => w.path === '/experiences/experience-1/evidences')?.body
	).toMatchObject({ name: 'Lista de precios', criterion_ids: ['criterion-1'] });
});

test('sessions can be created on an empty date and summary can be confirmed', async ({
	page,
	api,
}) => {
	await page.goto(`${planningBase}/sessions`);
	await page.getByRole('button', { name: 'Crear', exact: true }).first().click();
	await page.getByLabel('Título de la sesión', { exact: true }).fill('Calculamos el cambio');
	await page.getByRole('button', { name: 'Guardar', exact: true }).click();
	await expect(page.getByText('Calculamos el cambio', { exact: true })).toBeVisible();
	expect(
		api.writes.some((w) => w.method === 'PUT' && w.path.endsWith('/sessions/2026-10-07'))
	).toBe(true);
	await page.getByRole('button', { name: 'Continuar', exact: true }).click();
	await page.getByRole('button', { name: 'Guardar experiencia', exact: true }).click();
	await expect(page).toHaveURL('/class/class-1/plan');
	expect(api.experience.status).toBe('planificada');
});

test('evidence scores and official level remain separate and null stays unset', async ({
	page,
	api,
}) => {
	await page.goto(studentRoute);
	const slider = page.getByRole('slider');
	await expect(slider).toHaveAttribute('aria-valuetext', 'Sin valorar');
	const official = page.getByRole('group', { name: 'Nivel de logro', exact: true });
	await expect(official.locator('input:checked')).toHaveCount(0);
	await slider.focus();
	await page.keyboard.press('Home');
	await page.keyboard.press('ArrowRight');
	await expect(slider).toHaveAttribute('aria-valuenow', '1');
	await expect(official.locator('input:checked')).toHaveCount(0);
	expect(
		api.writes.some((w) => w.path === '/assessments/numeric-1/scores' && w.body.raw_value === 1)
	).toBe(true);
	await official.getByRole('radio', { name: 'C · En inicio', exact: true }).check();
	await expect(official.locator('input:checked')).toHaveValue('C');
	expect(api.writes.find((w) => w.path.endsWith('/competency-levels'))?.body.level).toBe('C');
});

test('schools without internal grading show no numeric controls', async ({ page, api }) => {
	api.internal = false;
	await page.goto(studentRoute);
	await expect(page.getByText('Nivel de logro', { exact: true }).first()).toBeVisible();
	await expect(page.getByRole('slider')).toHaveCount(0);
	await page.goto(gradesRoute);
	await expect(page.getByText('Sistema interno de la IE')).toHaveCount(0);
	await page.getByRole('button', { name: /Prácticas/ }).click();
	await expect(page.getByRole('spinbutton')).toHaveCount(0);
});

test('a failed screen load offers retry and recovers', async ({ page, api }) => {
	api.failures.add('/classes/class-1/plan');
	await page.goto('/class/class-1/plan');
	await expect(page.getByRole('button', { name: 'Reintentar' })).toBeVisible();
	api.failures.clear();
	await page.getByRole('button', { name: 'Reintentar' }).click();
	await expect(page.getByRole('heading', { name: 'Tu trimestre', exact: true })).toBeVisible();
});

test('No entregó and final conclusions preserve their distinct contracts', async ({
	page,
	api,
}) => {
	let finishLevelSave!: () => void;
	const levelSave = new Promise<void>((resolve) => (finishLevelSave = resolve));
	await page.route('**/competency-levels', async (route) => {
		await levelSave;
		await route.fallback();
	});
	await page.goto(studentRoute);
	await page.getByRole('checkbox', { name: 'No entregó', exact: true }).first().check();
	await expect
		.poll(() => api.writes.some((w) => w.path === '/assessments/numeric-1/scores'))
		.toBe(true);
	expect(api.writes.find((w) => w.path === '/assessments/numeric-1/scores')?.body).toMatchObject({
		status: 'not_submitted',
	});
	const official = page.getByRole('group', { name: 'Nivel de logro', exact: true });
	await official.getByRole('radio', { name: 'C · En inicio', exact: true }).check();
	await page
		.getByLabel('Conclusión descriptiva', { exact: true })
		.fill('Explica sus procedimientos; debe practicar el cálculo de cambio.');
	finishLevelSave();
	await expect(official.getByRole('radio', { name: 'C · En inicio', exact: true })).toBeEnabled();
	await expect(page.getByLabel('Conclusión descriptiva', { exact: true })).toHaveValue(
		'Explica sus procedimientos; debe practicar el cálculo de cambio.'
	);
	await page.getByRole('button', { name: 'Guardar borrador', exact: true }).click();
	await expect
		.poll(() =>
			api.writes.some((w) => w.path.endsWith('/conclusions') && w.body.status === 'draft')
		)
		.toBe(true);
	await page.getByRole('button', { name: 'Marcar como final', exact: true }).click();
	await expect(page.getByText('Una conclusión final debe incluir recomendaciones')).toBeVisible();
	expect(api.writes.some((w) => w.path.endsWith('/conclusions') && w.body.status === 'final')).toBe(
		false
	);
	await page.getByRole('checkbox', { name: 'Incluye recomendaciones personalizadas' }).check();
	await expect(
		page.getByRole('checkbox', { name: 'Incluye recomendaciones personalizadas' })
	).toBeChecked();
	await page.getByRole('button', { name: 'Marcar como final', exact: true }).click();
	await expect
		.poll(() =>
			api.writes.some(
				(w) =>
					w.path.endsWith('/conclusions') &&
					w.body.status === 'final' &&
					w.body.includes_recommendations === true
			)
		)
		.toBe(true);
});

test('personal notes require a score and do not assert an official level', async ({
	page,
	api,
}) => {
	await page.goto(gradesRoute);
	await page.getByRole('button', { name: 'Añadir nota personal' }).click();
	const dialog = page.getByRole('dialog', { name: 'Añadir evaluación' });
	await dialog.getByLabel('Título', { exact: true }).fill('Práctica personal');
	await expect(dialog.getByRole('button', { name: 'Guardar', exact: true })).toBeDisabled();
	await dialog.getByLabel('Nota', { exact: true }).fill('0');
	await dialog.getByRole('button', { name: 'Guardar', exact: true }).click();
	await expect.poll(() => api.writes.some((w) => w.path.endsWith('/practice-scores'))).toBe(true);
	expect(api.writes.find((w) => w.path.endsWith('/practice-scores'))?.body.raw_value).toBe(0);
	expect(api.writes.some((w) => w.path.endsWith('/competency-levels'))).toBe(false);
});

test('missing pages use the shared shell and offer a route home', async ({ page, api }) => {
	await page.goto('/missing-page');
	await expect(page.getByRole('heading', { name: 'No encontramos esta página' })).toBeVisible();
	await page.getByRole('link', { name: 'Volver al inicio', exact: true }).click();
	await expect(page).toHaveURL('/');
	expect(api.unexpected).toEqual([]);
});

test('profile shows basic identity and teaching information, with class access and confirmed logout', async ({
	page,
	api,
}) => {
	await page.goto('/profile');
	await expect(page.getByRole('heading', { name: 'María Santos', exact: true })).toBeVisible();
	await expect(page.getByRole('heading', { name: 'Mi colegio', exact: true })).toBeVisible();
	await expect(page.getByText('Colegio San Felipe', { exact: true })).toBeVisible();
	await expect(page.getByText('Lima', { exact: true })).toBeVisible();
	await expect(page.getByText('Primero de secundaria', { exact: true })).toBeVisible();
	await expect(
		page.getByText(/Asistencias registradas|Notas de voz|Evaluaciones registradas|Semanales/)
	).toHaveCount(0);
	await page.getByRole('link', { name: 'Matemática · Primero de secundaria', exact: true }).click();
	await expect(page).toHaveURL('/class/class-1');
	await page.goBack();
	await page.getByRole('button', { name: 'Cerrar sesión', exact: true }).click();
	const dialog = page.getByRole('alertdialog', { name: '¿Cerrar sesión?' });
	await dialog.getByRole('button', { name: 'Cancelar', exact: true }).click();
	await expect(dialog).not.toBeVisible();
	expect(api.writes.some((write) => write.path === '/auth/logout')).toBe(false);
	await page.getByRole('button', { name: 'Cerrar sesión', exact: true }).click();
	await dialog.getByRole('button', { name: 'Cerrar sesión', exact: true }).click();
	await expect(page).toHaveURL('/login');
	expect(api.writes.some((write) => write.path === '/auth/logout')).toBe(true);
});

test('profile omits unavailable city and teaching details without example placeholders', async ({
	page,
	api,
}) => {
	await page.route('**/api/v1/profile', (route) =>
		route.fulfill({
			json: {
				display_name: 'María Santos',
				title: null,
				tenant_name: 'Colegio San Felipe',
				tenant_city: null,
				classes_by_grade: null,
			},
		})
	);
	await page.goto('/profile');
	await expect(page.getByRole('heading', { name: 'María Santos', exact: true })).toBeVisible();
	await expect(page.getByText('Docente', { exact: true })).toBeVisible();
	await expect(page.getByRole('heading', { name: 'Mi enseñanza', exact: true })).toHaveCount(0);
	await expect(page.getByText('Lima', { exact: true })).toHaveCount(0);
	await expect(page.getByRole('button', { name: 'Cerrar sesión', exact: true })).toBeVisible();
	expect(api.unexpected).toEqual([]);
});
