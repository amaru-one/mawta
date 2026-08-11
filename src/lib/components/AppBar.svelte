<script lang="ts">
	import AccountMenu from './AccountMenu.svelte';
	import NotificationBell from './NotificationBell.svelte';
</script>

<div class="app-bar">
	<div class="app-bar-inner">
		<span class="app-name">yanay</span>
		<div class="actions">
			<NotificationBell />
			<AccountMenu />
		</div>
	</div>
</div>

<style>
	.app-bar {
		position: sticky;
		top: 0;
		z-index: 900;
		background: var(--white);
		border-bottom: 1px solid var(--gray-200);
	}

	.app-bar-inner {
		max-width: 1200px;
		margin: 0 auto;
		padding: var(--space-sm) var(--space-lg);
		display: flex;
		align-items: center;
		justify-content: space-between;
	}

	.app-name {
		font-size: 15px;
		font-weight: 700;
		letter-spacing: 0.3px;
	}

	.actions {
		display: flex;
		align-items: center;
		gap: var(--space-xs);
	}

	@media (min-width: 768px) {
		.app-bar-inner {
			padding: var(--space-sm) var(--space-xl);
		}
	}
</style>
