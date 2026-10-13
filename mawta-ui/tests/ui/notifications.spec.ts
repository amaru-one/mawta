import { test, expect } from './fixtures';

const readPath = (id: string) => `/notifications/${id}/read`;

test('marking under a filter only touches the notifications that filter shows', async ({
	page,
	api,
}) => {
	api.notifications.push({
		...api.notifications[0],
		id: 'notification-2',
		kind: 'reminder',
		title: 'Recuerda la entrega',
		read_at: null,
	});
	await page.goto('/notifications');
	await page.getByRole('button', { name: 'Alertas', exact: true }).click();
	await page.getByRole('button', { name: 'Marcar estas como leídas', exact: true }).click();
	await expect
		.poll(() => api.writes.map((w) => w.path).filter((p) => p.endsWith('/read')))
		.toEqual([readPath('notification-1')]);
	expect(api.unexpected).toEqual([]);
});

test('a refused mark rolls the row back to unread and offers a retry', async ({ page, api }) => {
	api.failures.add(readPath('notification-1'));
	await page.goto('/notifications');
	await page.getByRole('button', { name: 'Marcar todas leídas', exact: true }).click();
	await expect(page.getByRole('alert')).toContainText('No se marcaron 1 de 1 notificaciones');
	await expect(page.getByText('Sin leer.', { exact: true })).toHaveCount(1);

	api.failures.delete(readPath('notification-1'));
	await page.getByRole('button', { name: 'Reintentar', exact: true }).click();
	await expect(page.getByText('Sin leer.', { exact: true })).toHaveCount(0);
	expect(api.unexpected).toEqual([]);
});
