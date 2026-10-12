import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
	testDir: './tests/ui',
	fullyParallel: true,
	timeout: 30_000,
	expect: { timeout: 7_000 },
	workers: 3,
	reporter: [['list'], ['html', { open: 'never' }]],
	use: {
		baseURL: 'http://127.0.0.1:4173',
		viewport: { width: 390, height: 844 },
		trace: 'retain-on-failure',
		screenshot: 'only-on-failure',
		timezoneId: 'America/Lima',
	},
	projects: [
		{
			name: 'chromium',
			use: { ...devices['Desktop Chrome'], viewport: { width: 390, height: 844 } },
		},
		{
			name: 'webkit',
			use: { ...devices['Desktop Safari'], viewport: { width: 390, height: 844 } },
		},
	],
	webServer: [
		{
			command: 'bun run dev --host 127.0.0.1 --port 4173 --strictPort',
			url: 'http://127.0.0.1:4173',
			reuseExistingServer: false,
		},
	],
});
