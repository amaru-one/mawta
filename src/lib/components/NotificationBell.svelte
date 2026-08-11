<script lang="ts">
	import { scale } from 'svelte/transition';
	import { hapticTap } from '$lib/haptics';
	import { markAllNotificationsRead, markNotificationRead } from '$lib/notifications';
	import { notifications, unreadNotificationCount } from '$lib/stores';
	import type { AppNotification } from '$lib/types';

	let open = $state(false);

	const relativeTime = (date: Date): string => {
		const minutes = Math.round((Date.now() - date.getTime()) / 60000);
		if (minutes < 1) return 'just now';
		if (minutes < 60) return `${minutes}m ago`;
		const hours = Math.round(minutes / 60);
		if (hours < 24) return `${hours}h ago`;
		return `${Math.round(hours / 24)}d ago`;
	};

	const toggle = (): void => {
		hapticTap();
		open = !open;
	};

	const close = (): void => {
		open = false;
	};

	const selectNotification = (n: AppNotification): void => {
		if (!n.read) markNotificationRead(n.id);
	};
</script>

<div class="wrap">
	<button
		class="bell pressable"
		onclick={toggle}
		aria-label="Notifications"
		aria-haspopup="true"
		aria-expanded={open}
	>
		<svg viewBox="0 0 24 24" fill="currentColor" class="bell-icon">
			<path
				d="M12 22c1.1 0 2-.9 2-2h-4c0 1.1.89 2 2 2zm6-6v-5c0-3.07-1.64-5.64-4.5-6.32V4c0-.83-.67-1.5-1.5-1.5s-1.5.67-1.5 1.5v.68C7.63 5.36 6 7.92 6 11v5l-2 2v1h16v-1l-2-2z"
			/>
		</svg>
		{#if $unreadNotificationCount > 0}
			<span class="badge">{$unreadNotificationCount > 9 ? '9+' : $unreadNotificationCount}</span>
		{/if}
	</button>

	{#if open}
		<div
			class="backdrop"
			onclick={close}
			onkeydown={(e) => e.key === 'Escape' && close()}
			role="button"
			tabindex="-1"
			aria-label="Close notifications"
		></div>
		<div
			class="panel"
			role="dialog"
			aria-label="Notifications"
			tabindex="-1"
			in:scale={{ start: 0.95, duration: 150 }}
			out:scale={{ start: 0.95, duration: 150 }}
			onkeydown={(e) => e.key === 'Escape' && close()}
		>
			<div class="panel-header">
				<span class="panel-title">Notifications</span>
				{#if $unreadNotificationCount > 0}
					<button class="mark-all pressable" onclick={markAllNotificationsRead}>
						Mark all read
					</button>
				{/if}
			</div>
			{#if $notifications.length === 0}
				<p class="empty">No notifications.</p>
			{:else}
				<ul class="list">
					{#each $notifications as n (n.id)}
						<li>
							<button
								class="item pressable"
								class:unread={!n.read}
								onclick={() => selectNotification(n)}
							>
								<span class="dot" class:visible={!n.read}></span>
								<span class="body">
									<span class="line1">
										{#if n.studentName}<strong>{n.studentName}</strong>{/if}
										<span class="type" class:tip={n.type === 'tip'}>
											{n.type === 'risk' ? 'At risk' : 'AI tip'}
										</span>
									</span>
									<span class="message">{n.message}</span>
									<span class="time">{relativeTime(n.createdAt)}</span>
								</span>
							</button>
						</li>
					{/each}
				</ul>
			{/if}
		</div>
	{/if}
</div>

<style>
	.wrap {
		position: relative;
	}

	.bell {
		position: relative;
		display: inline-flex;
		align-items: center;
		justify-content: center;
		width: 40px;
		height: 40px;
		border: none;
		background: transparent;
		color: var(--neutral-900);
		border-radius: 50%;
		cursor: pointer;
	}

	.bell:hover {
		background: var(--gray-100);
	}

	.bell-icon {
		width: 22px;
		height: 22px;
	}

	.badge {
		position: absolute;
		top: 4px;
		right: 4px;
		min-width: 16px;
		height: 16px;
		padding: 0 3px;
		border-radius: 8px;
		background: var(--black);
		color: var(--white);
		font-size: 10px;
		font-weight: 700;
		line-height: 16px;
		text-align: center;
	}

	.backdrop {
		position: fixed;
		inset: 0;
		z-index: 1000;
		cursor: default;
	}

	.panel {
		position: absolute;
		top: calc(100% + 8px);
		right: 0;
		z-index: 1001;
		width: 320px;
		max-width: calc(100vw - 32px);
		max-height: 420px;
		overflow-y: auto;
		background: var(--white);
		border-radius: var(--radius-md);
		box-shadow: var(--shadow-lg);
		border: 1px solid var(--gray-200);
	}

	.panel-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: var(--space-md) var(--space-lg);
		border-bottom: 1px solid var(--gray-200);
		position: sticky;
		top: 0;
		background: var(--white);
	}

	.panel-title {
		font-size: 14px;
		font-weight: 700;
	}

	.mark-all {
		border: none;
		background: transparent;
		color: var(--neutral-600);
		font-size: 12px;
		font-weight: 600;
		cursor: pointer;
		padding: 4px;
	}

	.mark-all:hover {
		color: var(--black);
	}

	.empty {
		padding: var(--space-xl) var(--space-lg);
		text-align: center;
		color: var(--neutral-600);
		font-size: 14px;
	}

	.list {
		list-style: none;
		margin: 0;
		padding: 0;
	}

	.item {
		display: flex;
		align-items: flex-start;
		gap: var(--space-sm);
		width: 100%;
		padding: var(--space-md) var(--space-lg);
		border: none;
		background: transparent;
		text-align: left;
		cursor: pointer;
		border-bottom: 1px solid var(--gray-100);
	}

	.item:hover {
		background: var(--gray-50);
	}

	.item.unread {
		background: var(--gray-50);
	}

	.dot {
		width: 8px;
		height: 8px;
		min-width: 8px;
		margin-top: 6px;
		border-radius: 50%;
		visibility: hidden;
		background: var(--black);
	}

	.dot.visible {
		visibility: visible;
	}

	.body {
		display: flex;
		flex-direction: column;
		gap: 2px;
		min-width: 0;
	}

	.line1 {
		display: flex;
		align-items: center;
		gap: var(--space-xs);
		font-size: 13px;
	}

	.type {
		font-size: 10px;
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.4px;
		color: var(--neutral-600);
		background: var(--gray-200);
		padding: 2px 6px;
		border-radius: var(--radius-xs);
	}

	.type.tip {
		background: var(--gray-100);
	}

	.message {
		font-size: 13px;
		color: var(--neutral-900);
		white-space: normal;
	}

	.time {
		font-size: 11px;
		color: var(--neutral-600);
	}
</style>
