import adapter from '@sveltejs/adapter-static';
import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vite';

export default defineConfig({
	plugins: [
		sveltekit({
			compilerOptions: {
				// Force runes mode for the project, except for libraries. Can be removed in svelte 6.
				runes: ({ filename }) =>
					filename.split(/[/\\]/).includes('node_modules') ? undefined : true,
			},

			// SPA build: every route falls back to index.html and resolves client-side.
			adapter: adapter({ fallback: 'index.html' }),
		}),
	],
	// Expose PUBLIC_* vars on import.meta.env (Vite only exposes VITE_* by default).
	// Missing vars stay undefined instead of failing the build like $env/static would.
	envPrefix: ['VITE_', 'PUBLIC_'],
	server: {
		// Same-origin API in dev — mirrors the production reverse proxy, so no CORS.
		proxy: {
			'/api': 'http://localhost:8080',
			'/healthz': 'http://localhost:8080',
		},
	},
});
