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
			testIgnore: /flag\.spec\.ts/,
		},
		{
			name: 'webkit',
			use: { ...devices['Desktop Safari'], viewport: { width: 390, height: 844 } },
			testIgnore: /flag\.spec\.ts/,
		},
		{
			name: 'planning-disabled',
			use: { ...devices['Desktop Chrome'], baseURL: 'http://127.0.0.1:4174' },
			testMatch: /flag\.spec\.ts/,
		},
	],
	webServer: [
		{
			command: 'bun run dev --host 127.0.0.1 --port 4173 --strictPort',
			url: 'http://127.0.0.1:4173',
			env: { PUBLIC_PLANNING_ENABLED: 'true', PUBLIC_PLANNING_API: 'real' },
			reuseExistingServer: false,
		},
		{
			command: 'bun run dev --host 127.0.0.1 --port 4174 --strictPort',
			url: 'http://127.0.0.1:4174',
			env: { PUBLIC_PLANNING_ENABLED: 'false', PUBLIC_PLANNING_API: 'real' },
			reuseExistingServer: false,
		},
	],
});
