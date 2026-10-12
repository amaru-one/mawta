<script lang="ts">
	import { ConfirmDialog } from '$lib/design-system';
	let {
		title,
		description,
		confirmLabel,
		onconfirm,
		oncancel,
	}: {
		title: string;
		description: string;
		confirmLabel: string;
		onconfirm: () => void;
		oncancel: () => void;
	} = $props();
	let open = $state(true);
</script>

<ConfirmDialog bind:open {title} {description} {confirmLabel} {onconfirm} {oncancel} />
