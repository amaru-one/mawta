<script lang="ts">
	import { onDestroy, type Snippet } from 'svelte';
	import IconButton from './IconButton.svelte';
	const uid = $props.id();
	let {
		open = $bindable(false),
		title,
		description,
		children,
		actions,
		onclose,
		role = 'dialog',
	}: {
		open?: boolean;
		title: string;
		description?: string;
		children?: Snippet;
		actions?: Snippet;
		onclose?: () => void;
		role?: 'dialog' | 'alertdialog';
	} = $props();
	let element: HTMLDialogElement;
	let previousFocus: HTMLElement | null = null;
	$effect(() => {
		if (!element) return;
		if (open && !element.open) {
			previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
			element.showModal();
		} else if (!open && element.open) element.close();
	});
	function keepFocus(event: KeyboardEvent) {
		if (event.key !== 'Tab') return;
		const controls = Array.from(
			element.querySelectorAll<HTMLElement>(
				'button:not(:disabled), a[href], input:not(:disabled):not([type="hidden"]), select:not(:disabled), textarea:not(:disabled), [tabindex]'
			)
		).filter(
			(control) =>
				control.tabIndex >= 0 && !control.closest('[inert]') && control.getClientRects().length > 0
		);
		const first = controls[0];
		const last = controls[controls.length - 1];
		if (!first || !last) {
			event.preventDefault();
			return;
		}
		const current = controls.indexOf(document.activeElement as HTMLElement);
		const next = (current + (event.shiftKey ? -1 : 1) + controls.length) % controls.length;
		event.preventDefault();
		controls[next].focus();
	}
	function close() {
		open = false;
	}
	function restoreFocus() {
		if (previousFocus?.isConnected) previousFocus.focus({ preventScroll: true });
	}
	function closed() {
		open = false;
		restoreFocus();
		onclose?.();
	}
	onDestroy(() => {
		if (element?.open) {
			element.close();
			restoreFocus();
		}
	});
</script>

<dialog
	bind:this={element}
	class="mw-dialog"
	{role}
	aria-labelledby="{uid}-title"
	aria-describedby={description ? `${uid}-description` : undefined}
	onclose={closed}
	onkeydown={keepFocus}
>
	<div class="mw-dialog__head">
		<h2 id="{uid}-title" class="mw-text mw-text--heading">{title}</h2>
		<IconButton icon="x" label="Cerrar diálogo" onclick={close} />
	</div>
	{#if description}<p id="{uid}-description" class="mw-text mw-text--body">{description}</p>{/if}
	{#if children}<div class="mw-dialog__body">{@render children()}</div>{/if}
	{#if actions}<div class="mw-dialog__actions">{@render actions()}</div>{/if}
</dialog>
