<script lang="ts">
	import {
		Button,
		DesignSystem,
		Disclosure,
		Field,
		IconButton,
		TopBar,
	} from '../../src/lib/design-system';
	import AppToast from '../../src/lib/components/Toast.svelte';
	import LevelSelector from '../../src/lib/components/LevelSelector.svelte';
	import { showToast } from '../../src/lib/toast';
	import type { Tier } from '../../src/lib/levels';
	let { onaction = () => {} }: { onaction?: () => void } = $props();
	let control: HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement | null = $state(null);
	let level: Tier | null = $state(null);
</script>

<DesignSystem>
	<TopBar title="Mi clase" backHref="/class/example" identityHref="/profile" />
	<Button href="/class/example">Abrir clase</Button>
	<Button href="/class/example" disabled onclick={onaction}>Enlace deshabilitado</Button>
	<IconButton href="/notifications" icon="bell" label="Abrir notificaciones" />
	<Field label="Buscar alumno" bind:control />
	<Button onclick={() => control?.focus()}>Enfocar búsqueda</Button>
	<Disclosure>{#snippet summary()}Evidencias{/snippet}<Field label="Descripción" /></Disclosure>
	<LevelSelector {level} onselect={(value) => (level = value)} />
	<Button onclick={() => showToast('Guardado anterior')}>Primer aviso</Button>
	<Button onclick={() => showToast('Quitado reciente', { onUndo: onaction })}>Segundo aviso</Button>
	<AppToast />
</DesignSystem>
