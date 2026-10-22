import { expect, test, vi } from 'vitest';
import { flushSync } from 'svelte';
import { render } from 'vitest-browser-svelte';
import { page, userEvent } from 'vitest/browser';
import MigrationFixture from './MigrationFixture.svelte';

test('navigation buttons render native links and disabled links cannot activate', async () => {
	const onaction = vi.fn();
	const screen = await render(MigrationFixture, { onaction });
	await expect
		.element(screen.getByRole('link', { name: 'Abrir clase', exact: true }))
		.toHaveAttribute('href', '/class/example');
	await expect
		.element(screen.getByRole('link', { name: 'Volver', exact: true }))
		.toHaveAttribute('href', '/class/example');
	await expect
		.element(screen.getByRole('link', { name: 'Abrir notificaciones' }))
		.toHaveAttribute('href', '/notifications');
	const disabled = screen.getByRole('link', { name: 'Enlace deshabilitado' });
	await expect.element(disabled).not.toHaveAttribute('href');
	(disabled.element() as HTMLElement).click();
	expect(onaction).not.toHaveBeenCalled();
});

test('fields expose focus and disclosures support keyboard activation', async () => {
	const screen = await render(MigrationFixture);
	await screen.getByRole('button', { name: 'Enfocar búsqueda' }).click();
	await expect.element(screen.getByRole('textbox', { name: 'Buscar alumno' })).toHaveFocus();
	const disclosure = screen.getByRole('button', { name: 'Evidencias', exact: true });
	await expect.element(disclosure).toHaveAttribute('aria-expanded', 'false');
	(disclosure.element() as HTMLElement).focus();
	await userEvent.keyboard('{Enter}');
	await expect.element(disclosure).toHaveAttribute('aria-expanded', 'true');
	await expect
		.element(screen.getByRole('textbox', { name: 'Descripción', exact: true }))
		.toBeVisible();
});

test('official level starts unset and native radios support arrow keys', async () => {
	const screen = await render(MigrationFixture);
	const first = screen.getByRole('radio', { name: 'AD · Logro destacado' });
	await expect.element(first).not.toBeChecked();
	(first.element() as HTMLElement).focus();
	await userEvent.keyboard('{ArrowRight}');
	await expect.element(screen.getByRole('radio', { name: 'A · Logro esperado' })).toBeChecked();
	await expect.element(screen.getByRole('radio', { name: 'C · En inicio' })).not.toBeChecked();
});

test('replacing a toast cancels its old timer and undo remains available for seven seconds', async () => {
	vi.useFakeTimers();
	try {
		const onaction = vi.fn();
		const screen = await render(MigrationFixture, { onaction });
		(screen.getByRole('button', { name: 'Primer aviso' }).element() as HTMLElement).click();
		flushSync();
		await vi.advanceTimersByTimeAsync(1500);
		(screen.getByRole('button', { name: 'Segundo aviso' }).element() as HTMLElement).click();
		flushSync();
		await vi.advanceTimersByTimeAsync(1000);
		const status = page.getByRole('status').element();
		expect(status.textContent).toContain('Quitado reciente');
		await vi.advanceTimersByTimeAsync(5000);
		const undo = page.getByRole('button', { name: 'Deshacer', exact: true });
		await expect.element(undo).toBeVisible();
		(undo.element() as HTMLElement).click();
		flushSync();
		expect(onaction).toHaveBeenCalledTimes(1);
		await vi.advanceTimersByTimeAsync(2000);
		expect(status.matches(':popover-open')).toBe(false);
	} finally {
		vi.useRealTimers();
	}
});
