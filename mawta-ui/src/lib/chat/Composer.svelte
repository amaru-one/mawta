<script lang="ts">
	import { Icon } from '$lib/design-system';

	let {
		busy = false,
		disabled = false,
		onsend,
		onstop,
	}: {
		busy?: boolean;
		disabled?: boolean;
		onsend: (text: string) => void;
		onstop: () => void;
	} = $props();

	let text = $state('');
	let field: HTMLTextAreaElement | undefined = $state();
	const canSend = $derived(!busy && !disabled && text.trim() !== '');

	function autosize(): void {
		if (!field) return;
		field.style.height = 'auto';
		field.style.height = `${Math.min(field.scrollHeight, 180)}px`;
	}

	function submit(event?: Event): void {
		event?.preventDefault();
		if (busy) {
			onstop();
			return;
		}
		if (!canSend) return;
		onsend(text.trim());
		text = '';
		queueMicrotask(autosize);
	}

	function onkeydown(event: KeyboardEvent): void {
		// Enter sends; Shift+Enter is a new line; an IME composition is left alone.
		if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) submit(event);
	}

	export function focus(): void {
		field?.focus();
	}
</script>

<form class="composer" onsubmit={submit}>
	<div class="box">
		<label for="chat-input" class="mw-sr-only">Escribe tu pregunta</label>
		<textarea
			id="chat-input"
			bind:this={field}
			bind:value={text}
			oninput={autosize}
			{onkeydown}
			rows="1"
			placeholder="Pregunta sobre tu colegio…"
			autocomplete="off"
			{disabled}></textarea>
		<button
			class="send"
			class:stop={busy}
			type="submit"
			aria-label={busy ? 'Detener respuesta' : 'Enviar'}
			disabled={!busy && !canSend}
		>
			<Icon name={busy ? 'stop' : 'arrow-up'} size={20} />
		</button>
	</div>
	<p class="hint">Responde con los datos registrados en Mawta. No emite juicios sobre personas.</p>
</form>

<style>
	.composer {
		padding: var(--mw-space-2) var(--mw-space-4);
		padding-bottom: max(var(--mw-space-3), env(safe-area-inset-bottom));
		background: linear-gradient(to bottom, rgb(255 255 255 / 0), var(--mw-surface-card) 24%);
	}
	.box {
		display: flex;
		align-items: flex-end;
		gap: var(--mw-space-2);
		max-width: var(--chat-measure, 760px);
		margin: 0 auto;
		padding: var(--mw-space-2) var(--mw-space-2) var(--mw-space-2) var(--mw-space-4);
		border: 1px solid var(--mw-line-control);
		border-radius: var(--mw-radius-xl);
		background: var(--mw-surface-card);
		box-shadow: var(--mw-shadow-card);
	}
	.box:focus-within {
		border-color: var(--mw-accent);
		box-shadow: 0 0 0 3px rgb(79 70 229 / 15%);
	}
	textarea {
		flex: 1;
		min-height: var(--mw-touch-target);
		max-height: 180px;
		padding: 11px 0;
		border: 0;
		outline: 0;
		resize: none;
		background: transparent;
		font-size: 16px;
		line-height: 22px;
	}
	/* The box shows the focus (focus-within); a second ring on the field doubles it. */
	textarea:focus-visible {
		outline: none;
	}
	textarea::placeholder {
		color: var(--mw-ink-muted);
	}
	.send {
		display: inline-flex;
		flex: 0 0 auto;
		align-items: center;
		justify-content: center;
		width: var(--mw-touch-target);
		height: var(--mw-touch-target);
		border-radius: var(--mw-radius-lg);
		background: var(--mw-accent);
		color: var(--mw-on-accent);
		transition:
			background-color var(--mw-duration-fast) ease,
			opacity var(--mw-duration-fast) ease;
	}
	.send:disabled {
		opacity: 0.4;
	}
	.send.stop {
		background: var(--mw-ink);
	}
	.hint {
		max-width: var(--chat-measure, 760px);
		margin: var(--mw-space-2) auto 0;
		color: var(--mw-ink-muted);
		font-size: var(--mw-type-caption-size);
		line-height: var(--mw-type-caption-line);
		text-align: center;
	}
</style>
