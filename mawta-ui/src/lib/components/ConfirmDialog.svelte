<script lang="ts">
	import { ConfirmDialog } from '$lib/design-system';
	let {
		title,
		description,
		confirmLabel,
		tone = 'default',
		onconfirm,
		oncancel,
	}: {
		title: string;
		description: string;
		confirmLabel: string;
		tone?: 'default' | 'danger';
		onconfirm: () => void;
		oncancel: () => void;
	} = $props();
	let open = $state(true);
</script>

<ConfirmDialog bind:open {title} {description} {confirmLabel} {tone} {onconfirm} {oncancel} />
