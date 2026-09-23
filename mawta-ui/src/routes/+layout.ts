// MediaRecorder and Web Audio are browser-only; the whole app is client-side.
// Served as an SPA (adapter-static fallback) — no prerendered routes, since
// dynamic routes use server-issued UUIDs that can't be enumerated at build time.
export const ssr = false;
export const prerender = false;
