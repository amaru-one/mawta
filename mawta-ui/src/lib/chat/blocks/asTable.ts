// Until the charts land (LayerChart, its own plan), a stacked-bars or matrix
// block is shown as a plain table with the same numbers.
import type { MatrixBlock, StackedBarsBlock, TableBlock } from '../types';

export function stackedBarsAsTable(block: StackedBarsBlock): TableBlock {
	return {
		tipo: 'tabla',
		titulo: block.titulo,
		columnas: ['', ...block.categorias, 'Total'],
		filas: block.grupos.map((g) => [
			g.etiqueta,
			...g.valores,
			g.valores.reduce((sum, v) => sum + v, 0),
		]),
		nota: block.nota,
	};
}

export function matrixAsTable(block: MatrixBlock): TableBlock {
	return {
		tipo: 'tabla',
		titulo: block.titulo,
		columnas: ['', '', ...block.columnas],
		// The heading is written once, on the first row of its group; an empty
		// cell (sin nivel) shows as "—".
		filas: block.filas.map((f, i) => [
			i > 0 && block.filas[i - 1].grupo === f.grupo ? '' : f.grupo,
			f.etiqueta,
			...f.celdas,
		]),
		nota: block.nota,
	};
}
