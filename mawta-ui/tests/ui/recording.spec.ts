import { test, expect } from './fixtures';
import type { Page } from '@playwright/test';

async function media(page: Page, denied = false) {
	await page.addInitScript(
		({ denied }) => {
			const state = { starts: 0, stops: 0, tracksStopped: 0 };
			Object.assign(window, { __media: state });
			const track = {
				readyState: 'live',
				stop: () => {
					state.tracksStopped++;
					track.readyState = 'ended';
				},
			};
			Object.defineProperty(navigator, 'mediaDevices', {
				configurable: true,
				value: {
					getUserMedia: async () => {
						if (denied) throw new DOMException('Denied', 'NotAllowedError');
						track.readyState = 'live';
						return { getTracks: () => [track], getAudioTracks: () => [track] };
					},
				},
			});
			class Recorder {
				static isTypeSupported() {
					return true;
				}
				state = 'inactive';
				mimeType = 'audio/webm';
				ondataavailable: ((event: { data: Blob }) => void) | null = null;
				onstop: (() => void) | null = null;
				start() {
					this.state = 'recording';
					state.starts++;
				}
				stop() {
					this.state = 'inactive';
					state.stops++;
					this.ondataavailable?.({ data: new Blob(['audio'], { type: this.mimeType }) });
					this.onstop?.();
				}
			}
			class Context {
				state = 'running';
				currentTime = 0;
				destination = {};
				async resume() {}
				async decodeAudioData() {
					return { duration: 2 };
				}
				createBufferSource() {
					return { buffer: null, onended: null, connect() {}, start() {}, stop() {} };
				}
			}
			Object.assign(window, { MediaRecorder: Recorder, AudioContext: Context });
		},
		{ denied }
	);
}
async function selectStudent(page: Page) {
	await page.goto('/class/class-1/lesson/session-1');
	await page.getByLabel('Buscar alumno', { exact: true }).fill('Ana');
	await page.getByRole('option', { name: /Ana Quispe/ }).click();
	const control = page.getByRole('button', {
		name: 'Mantén presionado para grabar una nota de voz',
	});
	await expect(control).toBeEnabled();
	return control;
}

test('short taps discard; held recordings upload, play, pause, and delete', async ({
	page,
	api,
}) => {
	await media(page);
	await page.clock.install();
	const control = await selectStudent(page);
	await control.dispatchEvent('pointerdown', { pointerId: 1, button: 0 });
	await page.clock.runFor(150);
	await control.dispatchEvent('pointerup', { pointerId: 1, button: 0 });
	expect(api.writes.filter((w) => w.path.endsWith('/voice-notes'))).toHaveLength(0);
	await control.dispatchEvent('pointerdown', { pointerId: 2, button: 0 });
	await page.clock.runFor(600);
	await expect(control).toHaveAttribute('aria-pressed', 'true');
	await control.dispatchEvent('pointerup', { pointerId: 2, button: 0 });
	await expect(page.getByRole('group', { name: 'Nota de voz' })).toHaveCount(1);
	await expect.poll(() => api.writes.filter((w) => w.path.endsWith('/voice-notes')).length).toBe(1);
	await page.getByRole('button', { name: 'Reproducir nota', exact: true }).first().click();
	await expect(
		page.getByRole('button', { name: 'Pausar nota', exact: true }).first()
	).toBeVisible();
	await page.getByRole('button', { name: 'Pausar nota', exact: true }).first().click();
	await page.getByRole('button', { name: 'Eliminar nota', exact: true }).click();
	await expect(page.getByRole('alertdialog')).toBeVisible();
	await page.getByRole('button', { name: 'Eliminar', exact: true }).click();
	await expect(page.getByRole('group', { name: 'Nota de voz' })).toHaveCount(0);
	await expect
		.poll(() => api.writes.some((w) => w.path === '/voice-notes/voice-new/discard'))
		.toBe(true);
});

test('keyboard holds stop at 60 seconds and release does not duplicate upload', async ({
	page,
	api,
}) => {
	await media(page);
	await page.clock.install();
	const control = await selectStudent(page);
	await control.focus();
	await page.keyboard.down('Space');
	await page.clock.runFor(450);
	await expect(control).toHaveAttribute('aria-pressed', 'true');
	await page.clock.fastForward(60_000);
	await expect(control).toHaveAttribute('aria-pressed', 'false');
	await page.keyboard.up('Space');
	await expect.poll(() => api.writes.filter((w) => w.path.endsWith('/voice-notes')).length).toBe(1);
	expect(api.writes.find((w) => w.path.endsWith('/voice-notes'))?.body.duration_ms).toBe(60000);
});

test('microphone denial resets the control and displays retry guidance', async ({ page, api }) => {
	await media(page, true);
	const control = await selectStudent(page);
	await control.dispatchEvent('pointerdown', { pointerId: 1, button: 0 });
	await expect(page.getByRole('alert')).toContainText('No se pudo acceder al micrófono');
	await expect(control).toHaveAttribute('aria-pressed', 'false');
	expect(api.writes.filter((w) => w.path.endsWith('/voice-notes'))).toHaveLength(0);
});

test('leaving during a hold cancels capture and releases the microphone', async ({ page, api }) => {
	await media(page);
	await page.clock.install();
	const control = await selectStudent(page);
	await control.dispatchEvent('pointerdown', { pointerId: 1, button: 0 });
	await page.clock.runFor(500);
	// Exercise a client-side route teardown without releasing the held pointer.
	await page.evaluate(() => {
		const link = document.createElement('a');
		link.href = '/profile';
		document.body.append(link);
		link.click();
		link.remove();
	});
	await expect(page.getByRole('button', { name: 'Cerrar sesión', exact: true })).toBeVisible();
	expect(
		await page.evaluate(
			() => (window as unknown as { __media: { tracksStopped: number } }).__media.tracksStopped
		)
	).toBeGreaterThan(0);
	expect(api.writes.filter((w) => w.path.endsWith('/voice-notes'))).toHaveLength(0);
});
