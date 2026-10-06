import { defineConfig } from 'vitest/config';
import { svelte } from '@sveltejs/vite-plugin-svelte';
import { playwright } from '@vitest/browser-playwright';

export default defineConfig({
	plugins: [svelte({ configFile: false })],
	test: {
		include: ['tests/design-system/**/*.test.ts'],
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
