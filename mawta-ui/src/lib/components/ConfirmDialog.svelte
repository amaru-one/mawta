<script lang="ts">
	import { ConfirmDialog } from '$lib/design-system';
	let {
		title,
		text,
		confirmLabel,
		onconfirm,
		oncancel,
	}: {
		title: string;
		text: string;
		confirmLabel: string;
		onconfirm: () => void;
		oncancel: () => void;
	} = $props();
	let open = $state(true);
</script>

<ConfirmDialog bind:open {title} description={text} {confirmLabel} {onconfirm} {oncancel} />
