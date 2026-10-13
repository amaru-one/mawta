<script lang="ts">
	import '../../src/app.css';
	import {
		DesignSystem,
		Button,
		ButtonRow,
		Action,
		IconButton,
		Text,
		Card,
		Context,
		Field,
		Checkbox,
		CheckboxGroup,
		Segmented,
		CoverageMeter,
		StatusList,
		Notice,
		Toast,
		TopBar,
		StepNav,
		SessionRow,
		Dialog,
		ConfirmDialog,
		EmptyState,
		ErrorNotice,
		PendingDialog,
		LoadingState,
		type ToastMessage,
	} from '../../src/lib/design-system';
	let {
		scenario = 'overview',
		onaction = () => {},
		oncancel = () => {},
		ondismiss = () => {},
		oncontinue = () => {},
		toastValue = null,
		loading = false,
		disabled = false,
	}: {
		scenario?: string;
		onaction?: () => void;
		oncancel?: () => void;
		ondismiss?: (id: string | number) => void;
		oncontinue?: () => void;
		toastValue?: ToastMessage | null;
		loading?: boolean;
		disabled?: boolean;
	} = $props();
	let score = $state<number | null | undefined>();
	let title = $state('La tiendita escolar');
	let situation = $state('Organizamos la feria del aula.');
	let kind = $state('production');
	let checks = $state<string[]>([]);
	let open = $state(false);
	let confirmation = $state(false);
	let step = $state(0);
	let standalone = $state(false);
	let pendingOpen = $state(false);
	const options = [
		{ value: 'production', label: 'Producción' },
		{ value: 'performance', label: 'Actuación' },
		{ value: 'exam', label: 'Prueba escrita', disabled: true },
	];
</script>

<button style="border-radius: 3px" data-testid="outside-button">Outside action</button>
<input style="font-size: 14px" data-testid="outside-input" aria-label="Outside field" />
<div style="width: 320px; max-width: 100%;">
	<DesignSystem>
		{#if scenario === 'actions'}
			<ButtonRow
				><Button variant="primary" {loading} {disabled} onclick={onaction}
					>Guardar experiencia</Button
				><Button>Crear criterio</Button></ButtonRow
			>
			<Action href="/target" {disabled} {loading}>Ver experiencia</Action>
			<IconButton icon="plus" label="Agregar criterio" onclick={onaction} />
		{:else if scenario === 'forms'}
			<form onsubmit={(event) => event.preventDefault()}>
				<Field
					label="Nombre"
					name="name"
					bind:value={title}
					help="Puedes editar el nombre."
					required
				/>
				<Field
					kind="textarea"
					label="Situación"
					name="situation"
					bind:value={situation}
					error="Describe el reto de tus estudiantes."
					rows={3}
				/>
				<Field kind="select" label="Tipo" name="kind" bind:value={kind} {options} />
				<Field
					type="number"
					label="Nota"
					name="score"
					min={0}
					max={20}
					step={0.5}
					bind:value={score}
				/>
				<output aria-label="Nota actual"
					>{score === null ? 'null' : typeof score}:{score ?? ''}</output
				>
				<CheckboxGroup
					label="Competencias"
					name="competencies"
					options={[
						{ value: 'quantity', label: 'Resuelve problemas de cantidad' },
						{ value: 'shape', label: 'Resuelve problemas de forma, movimiento y localización' },
						{
							value: 'data',
							label: 'Resuelve problemas de gestión de datos e incertidumbre',
							disabled: true,
						},
					]}
					bind:value={checks}
				/>
				<Checkbox
					label="Incluir recomendaciones"
					name="recommendations"
					bind:checked={standalone}
				/>
				<output aria-label="Valores"
					>{title}|{situation}|{kind}|{checks.join(',')}|{standalone}</output
				>
			</form>
		{:else if scenario === 'segmented'}
			<Segmented label="Tipo de evidencia" {options} bind:value={kind} onchange={onaction} />
			<output>{kind}</output>
		{:else if scenario === 'navigation'}
			<TopBar
				name="Rosa Q."
				school="Colegio de ejemplo · Huancayo"
				initials="RQ"
				notificationCount={3}
				onback={onaction}
				onnotifications={onaction}
				onidentity={onaction}
			/>
			<StepNav
				title={step === 0 ? 'Cantidad' : 'Regularidad'}
				index={step}
				total={2}
				onprevious={() => step--}
				onnext={() => step++}
			/>
		{:else if scenario === 'dialog'}
			<Button
				onclick={() => {
					open = true;
				}}>Abrir diálogo</Button
			>
			<Dialog
				bind:open
				title="Editar criterio"
				description="Modifica el texto del criterio."
				onclose={onaction}
			>
				<Field label="Texto del criterio" value="Plantea la operación." />
				{#snippet actions()}<Button
						onclick={() => {
							open = false;
						}}>Listo</Button
					>{/snippet}
			</Dialog>
			<Button
				onclick={() => {
					confirmation = true;
				}}>Quitar criterio</Button
			>
			<ConfirmDialog
				bind:open={confirmation}
				title="Quitar criterio"
				description="El criterio se quitará de la experiencia."
				confirmLabel="Confirmar"
				onconfirm={onaction}
				{oncancel}
			/>
		{:else if scenario === 'pending'}
			<Button
				onclick={() => {
					pendingOpen = true;
				}}>Continuar</Button
			>
			<PendingDialog bind:open={pendingOpen} count={3} onreview={onaction} {oncontinue} />
		{:else if scenario === 'error'}
			<ErrorNotice message="No pudimos guardar el nivel." onretry={onaction} retrying={loading} />
		{:else if scenario === 'danger'}
			<Button
				onclick={() => {
					confirmation = true;
				}}>Cerrar sesión</Button
			>
			<ConfirmDialog
				bind:open={confirmation}
				tone="danger"
				title="¿Cerrar sesión?"
				description="Tendrás que volver a entrar."
				confirmLabel="Cerrar sesión"
				onconfirm={onaction}
				{oncancel}
			/>
		{:else if scenario === 'toast'}
			<Toast message={toastValue} {ondismiss} />
		{:else}
			<Text as="h1" variant="display">Tu trimestre</Text>
			<Context><Text variant="label">Experiencia de aprendizaje</Text></Context>
			<Card>
				<Text variant="heading">La tiendita escolar</Text>
				<Text>Plantea la operación para calcular el total de una compra.</Text>
				{#snippet actions()}<Action variant="main" icon="check">Aceptar</Action><Action
						>Editar</Action
					><Action variant="remove" icon="trash">Quitar</Action>{/snippet}
			</Card>
			<CoverageMeter
				capabilities={[
					{ id: 'translate', label: 'Traduce', covered: true },
					{ id: 'argue', label: 'Argumenta', covered: false },
				]}
			/>
			<StatusList
				items={[
					{
						id: '1',
						name: 'Cantidad',
						status: 'done',
						label: 'Planificada',
						detail: '4 de 4 capacidades con criterio',
					},
					{ id: '2', name: 'Regularidad', status: 'due', label: 'Toca este trimestre' },
					{ id: '3', name: 'Forma', status: 'waiting', label: 'Puede esperar' },
				]}
			/>
			<Notice>Quedan criterios propuestos sin aceptar.</Notice>
			<Notice variant="attention">Falta mirar Argumenta. Puedes guardar igual.</Notice>
			<Notice variant="danger" live
				><strong>Faltan conclusiones.</strong> Complétalas para cerrar el periodo.</Notice
			>
			<SessionRow
				date="2026-06-12"
				title="Día de la feria"
				topics="Operaciones con números"
				evidence={{ name: 'Hoja de cuentas', href: '/evidence' }}
			/>
			<SessionRow date="2026-06-29" title="Feriado" off />
			<EmptyState
				title="Aún no hay evidencias"
				description="Agrega la primera evidencia."
				icon="clipboard-check"
			/>
			<LoadingState label="Cargando criterios…" />
		{/if}
	</DesignSystem>
</div>
