import { fileURLToPath } from 'node:url';
import { defineConfig } from 'vitest/config';
import { svelte } from '@sveltejs/vite-plugin-svelte';
import { playwright } from '@vitest/browser-playwright';

export default defineConfig({
	resolve: { alias: { $lib: fileURLToPath(new URL('./src/lib', import.meta.url)) } },
	plugins: [svelte({ configFile: false })],
	test: {
		include: ['tests/design-system/**/*.test.ts', 'tests/chat/**/*.test.ts'],
		browser: {
			enabled: true,
			headless: true,
			commands: {
				setReducedMotion: async ({ page }, reduced: boolean) => {
					await page.emulateMedia({ reducedMotion: reduced ? 'reduce' : 'no-preference' });
				},
			},
			provider: playwright(),
			instances: [{ browser: 'chromium' }, { browser: 'webkit' }],
		},
	},
});
