import { describe, expect, test, vi } from 'vitest';
import { userEvent, commands } from 'vitest/browser';
import { render } from 'vitest-browser-svelte';
import Fixture from './Fixture.svelte';
import { tick } from 'svelte';
import { get } from 'svelte/store';
import { dismissToast, showError, toast } from '../../src/lib/toast';
import { safeNext } from '../../src/lib/auth';

declare module 'vitest/browser' {
	interface BrowserCommands {
		setReducedMotion: (reduced: boolean) => Promise<void>;
	}
}

describe('Nítido interaction contracts', () => {
	test('buttons invoke callbacks and preserve native disabled/loading semantics', async () => {
		const action = vi.fn();
		const screen = await render(Fixture, { scenario: 'actions', onaction: action });
		const save = screen.getByRole('button', { name: 'Guardar experiencia' });
		await save.click();
		expect(action).toHaveBeenCalledTimes(1);
		await screen.rerender({ loading: true });
		await expect.element(save).toBeDisabled();
		await expect.element(save).toHaveAttribute('aria-busy', 'true');
		await expect
			.element(screen.getByRole('link', { name: 'Ver experiencia' }))
			.not.toHaveAttribute('href');
		await screen.rerender({ loading: false, disabled: true });
		await expect.element(save).toBeDisabled();
		await expect
			.element(screen.getByRole('link', { name: 'Ver experiencia' }))
			.toHaveAttribute('aria-disabled', 'true');
	});

	test('fields expose labels, descriptions, errors, bindings, and form values', async () => {
		const screen = await render(Fixture, { scenario: 'forms' });
		const name = screen.getByRole('textbox', { name: 'Nombre' });
		await name.fill('La feria escolar');
		await expect.element(name).toHaveAccessibleDescription('Puedes editar el nombre.');
		const situation = screen.getByRole('textbox', { name: 'Situación' });
		await expect.element(situation).toHaveAttribute('aria-invalid', 'true');
		await expect
			.element(situation)
			.toHaveAccessibleDescription('Describe el reto de tus estudiantes.');
		await situation.fill('Vendemos productos.');
		await screen.getByRole('combobox', { name: 'Tipo' }).selectOptions('performance');
		await screen.getByRole('checkbox', { name: 'Resuelve problemas de cantidad' }).click();
		await screen.getByRole('checkbox', { name: 'Incluir recomendaciones' }).click();
		await expect
			.element(screen.getByRole('status', { name: 'Valores' }))
			.toHaveTextContent('La feria escolar|Vendemos productos.|performance|quantity|true');
		await expect
			.element(
				screen.getByRole('checkbox', {
					name: 'Resuelve problemas de gestión de datos e incertidumbre',
				})
			)
			.toBeDisabled();
		const data = new FormData(name.element().closest('form')!);
		expect(data.get('name')).toBe('La feria escolar');
		expect(data.getAll('competencies')).toEqual(['quantity']);
	});

	test('checkbox rows support keyboard selection and visible focus', async () => {
		const screen = await render(Fixture, { scenario: 'forms' });
		const checkbox = screen.getByRole('checkbox', { name: 'Resuelve problemas de cantidad' });
		(checkbox.element() as HTMLInputElement).focus();
		await userEvent.keyboard(' ');
		await expect.element(checkbox).toBeChecked();
		const box = checkbox.element().nextElementSibling!;
		expect(getComputedStyle(box).outlineWidth).toBe('2px');
		expect(getComputedStyle(box).outlineOffset).toBe('2px');
	});

	test('segmented selection stays single and disabled options cannot be selected', async () => {
		const callback = vi.fn();
		const screen = await render(Fixture, { scenario: 'segmented', onaction: callback });
		const production = screen.getByRole('button', { name: 'Producción' });
		const performance = screen.getByRole('button', { name: 'Actuación' });
		await performance.click();
		await expect.element(performance).toHaveAttribute('aria-pressed', 'true');
		await expect.element(production).toHaveAttribute('aria-pressed', 'false');
		await expect.element(screen.getByRole('button', { name: 'Prueba escrita' })).toBeDisabled();
		expect(callback).toHaveBeenCalledWith('performance');
		(production.element() as HTMLButtonElement).focus();
		await userEvent.keyboard('{Enter}');
		await expect.element(production).toHaveAttribute('aria-pressed', 'true');
	});

	test('navigation guards the first and last step and exposes notification counts', async () => {
		const callback = vi.fn();
		const screen = await render(Fixture, { scenario: 'navigation', onaction: callback });
		const previous = screen.getByRole('button', { name: 'Anterior' });
		const next = screen.getByRole('button', { name: 'Siguiente' });
		await expect.element(previous).toBeDisabled();
		await next.click();
		await expect.element(next).toBeDisabled();
		await expect.element(screen.getByText('2 de 2 competencias')).toBeVisible();
		await previous.click();
		await expect.element(screen.getByText('1 de 2 competencias')).toBeVisible();
		await screen.getByRole('button', { name: 'Notificaciones, 3 sin leer' }).click();
		expect(callback).toHaveBeenCalledTimes(1);
	});

	test('dialog traps focus, closes with Escape, and restores the opener', async () => {
		const callback = vi.fn();
		const screen = await render(Fixture, { scenario: 'dialog', onaction: callback });
		const opener = screen.getByRole('button', { name: 'Abrir diálogo' });
		(opener.element() as HTMLButtonElement).focus();
		await userEvent.keyboard('{Enter}');
		const dialog = screen.getByRole('dialog', { name: 'Editar criterio' });
		await expect.element(dialog).toBeVisible();
		const dialogElement = dialog.element();
		await expect.element(dialog).toHaveAccessibleDescription('Modifica el texto del criterio.');
		for (let i = 0; i < 5; i++) {
			await userEvent.tab();
			expect(
				dialogElement.contains(document.activeElement),
				document.activeElement?.outerHTML
			).toBe(true);
		}
		await userEvent.keyboard('{Escape}');
		await expect.element(dialogElement).not.toBeVisible();
		await expect.element(opener).toHaveFocus();
		await expect.poll(() => callback.mock.calls.length).toBe(1);
	});

	test('confirmation fires exactly one confirmation or cancellation callback', async () => {
		const callback = vi.fn();
		const cancel = vi.fn();
		const screen = await render(Fixture, {
			scenario: 'dialog',
			onaction: callback,
			oncancel: cancel,
		});
		await screen.getByRole('button', { name: 'Quitar criterio' }).click();
		await screen.getByRole('button', { name: 'Confirmar' }).click();
		await expect.poll(() => callback.mock.calls.length).toBe(1);
		await screen.getByRole('button', { name: 'Quitar criterio' }).click();
		await screen.getByRole('button', { name: 'Cancelar' }).click();
		await expect.poll(() => cancel.mock.calls.length).toBe(1);
		expect(callback).toHaveBeenCalledTimes(1);
	});

	test('feedback describes coverage and status without relying on color', async () => {
		const screen = await render(Fixture);
		await expect.element(screen.getByText('Falta: Argumenta')).toBeVisible();
		await expect.element(screen.getByText('Planificada', { exact: true })).toBeVisible();
		await expect.element(screen.getByText('Puede esperar')).toBeVisible();
		await expect
			.element(screen.getByRole('alert'))
			.toHaveTextContent('Faltan conclusiones. Complétalas para cerrar el periodo.');
		await expect.element(screen.getByRole('status')).toHaveTextContent('Cargando criterios…');
		await expect.element(screen.getByText('Sin clase · no se cuenta')).toBeVisible();
		const date = screen.getByText('12', { exact: true }).element();
		expect(date.closest('time')?.dateTime).toBe('2026-06-12');
		expect(getComputedStyle(date).fontVariantNumeric).toBe('tabular-nums');
	});

	test('tokens and resets stay inside the design system with application CSS loaded', async () => {
		const screen = await render(Fixture, { scenario: 'actions' });
		const save = screen.getByRole('button', { name: 'Guardar experiencia' }).element();
		const style = getComputedStyle(save);
		expect(style.backgroundColor).toBe('rgb(79, 70, 229)');
		expect(style.backgroundImage).toBe('none');
		expect(style.borderRadius).toBe('12px');
		expect(save.getBoundingClientRect().height).toBeGreaterThanOrEqual(48);
		expect(getComputedStyle(screen.getByTestId('outside-button').element()).borderRadius).toBe(
			'3px'
		);
		expect(getComputedStyle(screen.getByTestId('outside-input').element()).fontSize).toBe('14px');
		const icon = screen.getByRole('button', { name: 'Agregar criterio' }).element();
		expect(icon.getBoundingClientRect().height).toBeGreaterThanOrEqual(40);
	});

	test('long form labels fit a 320px layout without horizontal overflow', async () => {
		const screen = await render(Fixture, { scenario: 'forms' });
		const group = screen.getByRole('group', { name: 'Competencias' }).element();
		expect(group.scrollWidth).toBeLessThanOrEqual(320);
		for (const control of group.querySelectorAll('label')) {
			expect(control.getBoundingClientRect().height).toBeGreaterThanOrEqual(48);
		}
	});

	test('toast dismissal uses the current message and cleans up stale timers', async () => {
		const dismiss = vi.fn();
		const screen = await render(Fixture, {
			scenario: 'toast',
			toastValue: { id: 'first', message: 'Primera', durationMs: 400 },
			ondismiss: dismiss,
		});
		await expect.element(screen.getByRole('status')).toHaveTextContent('Primera');
		await screen.rerender({ toastValue: { id: 'second', message: 'Segunda', durationMs: 40 } });
		await expect.poll(() => dismiss.mock.calls).toEqual([['second']]);
		await screen.rerender({ toastValue: null });
		await new Promise((resolve) => setTimeout(resolve, 450));
		expect(dismiss).toHaveBeenCalledTimes(1);
	});

	test('toast undo invokes the action once and keeps the inverse theme in the top layer', async () => {
		const action = vi.fn();
		const dismiss = vi.fn();
		const screen = await render(Fixture, {
			scenario: 'toast',
			toastValue: { id: 1, message: 'Criterio quitado', onaction: action },
			ondismiss: dismiss,
		});
		const toast = screen.getByRole('status');
		await expect.element(toast).toBeVisible();
		expect(getComputedStyle(toast.element()).backgroundColor).toBe('rgb(15, 23, 42)');
		await screen.getByRole('button', { name: 'Deshacer' }).click();
		expect(action).toHaveBeenCalledTimes(1);
		expect(dismiss).toHaveBeenCalledWith(1);
	});
});

test('toast defaults to two seconds, seven with an action, and clears timers on unmount', async () => {
	vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
	try {
		const dismiss = vi.fn();
		const screen = await render(Fixture, {
			scenario: 'toast',
			toastValue: { id: 'plain', message: 'Experiencia guardada' },
			ondismiss: dismiss,
		});
		await tick();
		await vi.advanceTimersByTimeAsync(1999);
		expect(dismiss).not.toHaveBeenCalled();
		await vi.advanceTimersByTimeAsync(1);
		expect(dismiss).toHaveBeenCalledWith('plain');
		dismiss.mockClear();
		await screen.rerender({
			toastValue: { id: 'undo', message: 'Criterio quitado', onaction: () => {} },
		});
		await vi.advanceTimersByTimeAsync(6999);
		expect(dismiss).not.toHaveBeenCalled();
		await vi.advanceTimersByTimeAsync(1);
		expect(dismiss).toHaveBeenCalledWith('undo');
		dismiss.mockClear();
		await screen.rerender({ toastValue: { id: 'unmount', message: 'Evidencia guardada' } });
		await screen.unmount();
		await vi.advanceTimersByTimeAsync(8000);
		expect(dismiss).not.toHaveBeenCalled();
	} finally {
		vi.useRealTimers();
	}
});

test('reduced-motion preference stops the spinner and control transitions', async () => {
	await commands.setReducedMotion(true);
	try {
		const screen = await render(Fixture, { scenario: 'actions', loading: true });
		const button = screen.getByRole('button', { name: 'Guardar experiencia' }).element();
		expect(getComputedStyle(button.querySelector('.mw-spinner')!).animationName).toBe('none');
		expect(getComputedStyle(button).transitionDuration).toBe('0s');
	} finally {
		await commands.setReducedMotion(false);
	}
});

test('numeric fields start empty, bind numbers, and preserve native empty values', async () => {
	const screen = await render(Fixture, { scenario: 'forms' });
	const score = screen.getByRole('spinbutton', { name: 'Nota', exact: true });
	await expect.element(score).toHaveAttribute('min', '0');
	await expect.element(score).toHaveAttribute('max', '20');
	await expect
		.element(screen.getByRole('status', { name: 'Nota actual' }))
		.toHaveTextContent('undefined:');
	await score.fill('8.5');
	await expect
		.element(screen.getByRole('status', { name: 'Nota actual' }))
		.toHaveTextContent('number:8.5');
	await score.fill('');
	await expect
		.element(screen.getByRole('status', { name: 'Nota actual' }))
		.toHaveTextContent('null:');
});

test('safeNext keeps same-origin paths and rejects off-site or login targets', () => {
	expect(safeNext('/class/class-1')).toBe('/class/class-1');
	for (const unsafe of ['//evil.test', '/\\evil.test', 'https://evil.test', '/login', null]) {
		expect(safeNext(unsafe)).toBeNull();
	}
});

test('showError stores an error tone with a retry action and a longer hold', () => {
	const retry = vi.fn();
	showError('No se guardó', { onRetry: retry });
	const current = get(toast)!;
	expect(current.tone).toBe('error');
	expect(current.undoLabel).toBe('Reintentar');
	expect(current.durationMs).toBe(6000);
	current.onUndo?.();
	expect(retry).toHaveBeenCalledTimes(1);
	dismissToast(current.id);
});

test('error toasts announce as alerts and hold their timer while hovered', async () => {
	const dismissed = vi.fn();
	const screen = await render(Fixture, {
		scenario: 'toast',
		ondismiss: dismissed,
		toastValue: { id: 'err', message: 'No se guardó', tone: 'error', durationMs: 300 },
	});
	const notice = screen.getByRole('alert');
	await expect.element(notice).toHaveTextContent('No se guardó');
	await userEvent.hover(notice.element());
	await new Promise((resolve) => setTimeout(resolve, 450));
	expect(dismissed).not.toHaveBeenCalled();
	await userEvent.unhover(notice.element());
	await new Promise((resolve) => setTimeout(resolve, 450));
	expect(dismissed).toHaveBeenCalledTimes(1);
});

test('error notices are announced and retry runs once, busy while retrying', async () => {
	const retry = vi.fn();
	const screen = await render(Fixture, { scenario: 'error', onaction: retry });
	await expect.element(screen.getByRole('alert')).toHaveTextContent('No pudimos guardar el nivel.');
	await screen.getByRole('button', { name: 'Reintentar' }).click();
	expect(retry).toHaveBeenCalledTimes(1);
	await screen.rerender({ loading: true });
	await expect.element(screen.getByRole('button', { name: 'Reintentar' })).toBeDisabled();
});

test('danger confirmations use the danger button and fire one decision', async () => {
	const confirm = vi.fn();
	const cancel = vi.fn();
	const screen = await render(Fixture, { scenario: 'danger', onaction: confirm, oncancel: cancel });
	await screen.getByRole('button', { name: 'Cerrar sesión' }).click();
	const dialog = screen.getByRole('alertdialog');
	const confirmButton = dialog.getByRole('button', { name: 'Cerrar sesión' });
	expect(getComputedStyle(confirmButton.element()).backgroundColor).toBe('rgb(180, 35, 24)');
	await confirmButton.click();
	expect(confirm).toHaveBeenCalledTimes(1);
	expect(cancel).not.toHaveBeenCalled();
});
