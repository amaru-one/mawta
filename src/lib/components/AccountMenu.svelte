<script lang="ts">
	import { scale } from 'svelte/transition';
	import { hapticTap } from '$lib/haptics';

	let menuOpen = $state(false);
	let showLogoutConfirm = $state(false);

	const toggleMenu = (): void => {
		hapticTap();
		menuOpen = !menuOpen;
	};

	const closeMenu = (): void => {
		menuOpen = false;
	};

	const openLogoutConfirm = (): void => {
		menuOpen = false;
		showLogoutConfirm = true;
	};

	const closeLogoutConfirm = (): void => {
		showLogoutConfirm = false;
	};

	// UI-only for now — no auth/session backend exists yet to actually log out of.
	const confirmLogout = (): void => {
		showLogoutConfirm = false;
	};
</script>

<div class="wrap">
	<button
		class="avatar pressable"
		onclick={toggleMenu}
		aria-label="Account menu"
		aria-haspopup="menu"
		aria-expanded={menuOpen}
	>
		T
	</button>

	{#if menuOpen}
		<div
			class="backdrop"
			onclick={closeMenu}
			onkeydown={(e) => e.key === 'Escape' && closeMenu()}
			role="button"
			tabindex="-1"
			aria-label="Close account menu"
		></div>
		<div
			class="menu"
			role="menu"
			aria-label="Account"
			tabindex="-1"
			in:scale={{ start: 0.95, duration: 150 }}
			out:scale={{ start: 0.95, duration: 150 }}
			onkeydown={(e) => e.key === 'Escape' && closeMenu()}
		>
			<button class="menu-item pressable" role="menuitem" onclick={openLogoutConfirm}>
				Log out
			</button>
		</div>
	{/if}
</div>

{#if showLogoutConfirm}
	<div
		class="logout-modal"
		in:scale={{ start: 0.95, duration: 150 }}
		out:scale={{ start: 0.95, duration: 150 }}
		onkeydown={(e) => e.key === 'Escape' && closeLogoutConfirm()}
		role="alertdialog"
		aria-modal="true"
		aria-labelledby="logout-title"
		tabindex="0"
	>
		<div
			class="modal-backdrop"
			onclick={closeLogoutConfirm}
			onkeydown={(e) => e.key === 'Escape' && closeLogoutConfirm()}
			role="button"
			tabindex="-1"
			aria-label="Close confirmation dialog"
		></div>
		<div class="modal-content">
			<p class="modal-title" id="logout-title">Log out?</p>
			<p class="modal-text">You'll need to sign back in to access your classes.</p>
			<div class="modal-actions">
				<button class="modal-cancel pressable" onclick={closeLogoutConfirm}> Cancel </button>
				<button class="modal-logout pressable" onclick={confirmLogout}> Log out </button>
			</div>
		</div>
	</div>
{/if}

<style>
	.wrap {
		position: relative;
	}

	.avatar {
		width: 36px;
		height: 36px;
		border-radius: 50%;
		border: none;
		background: var(--black);
		color: var(--white);
		font-size: 14px;
		font-weight: 700;
		cursor: pointer;
		display: inline-flex;
		align-items: center;
		justify-content: center;
	}

	.avatar:hover {
		background: var(--gray-800);
	}

	.backdrop {
		position: fixed;
		inset: 0;
		z-index: 1000;
		cursor: default;
	}

	.menu {
		position: absolute;
		top: calc(100% + 8px);
		right: 0;
		z-index: 1001;
		min-width: 160px;
		background: var(--white);
		border-radius: var(--radius-md);
		box-shadow: var(--shadow-lg);
		border: 1px solid var(--gray-200);
		padding: var(--space-xs);
	}

	.menu-item {
		display: block;
		width: 100%;
		padding: var(--space-sm) var(--space-md);
		border: none;
		background: transparent;
		text-align: left;
		font-size: 14px;
		font-weight: 600;
		color: var(--neutral-900);
		border-radius: var(--radius-sm);
		cursor: pointer;
	}

	.menu-item:hover {
		background: var(--gray-100);
	}

	.logout-modal {
		position: fixed;
		inset: 0;
		display: flex;
		align-items: center;
		justify-content: center;
		z-index: 2000;
	}

	.modal-backdrop {
		position: absolute;
		inset: 0;
		background: rgba(0, 0, 0, 0.5);
		cursor: pointer;
	}

	.modal-content {
		position: relative;
		background: var(--white);
		border-radius: 12px;
		padding: 24px;
		max-width: 320px;
		box-shadow: 0 20px 25px rgba(0, 0, 0, 0.15);
	}

	.modal-title {
		margin: 0 0 8px;
		font-size: 16px;
		font-weight: 700;
		color: var(--neutral-900);
	}

	.modal-text {
		margin: 0 0 20px;
		font-size: 14px;
		color: var(--neutral-600);
	}

	.modal-actions {
		display: flex;
		gap: 12px;
		justify-content: flex-end;
	}

	.modal-cancel {
		padding: 10px 16px;
		min-height: 36px;
		border-radius: 6px;
		background: var(--gray-200);
		color: var(--neutral-900);
		font-size: 14px;
		font-weight: 600;
		cursor: pointer;
		transition: all 150ms ease-out;
		border: none;
	}

	.modal-cancel:hover {
		background: var(--gray-300);
	}

	.modal-cancel:active {
		transform: scale(0.95);
	}

	.modal-logout {
		padding: 10px 16px;
		min-height: 36px;
		border-radius: 6px;
		background: var(--action-delete);
		color: var(--white);
		font-size: 14px;
		font-weight: 600;
		cursor: pointer;
		transition: all 150ms ease-out;
		border: none;
	}

	.modal-logout:hover {
		background: var(--action-delete-dark);
	}

	.modal-logout:active {
		transform: scale(0.95);
	}
</style>
