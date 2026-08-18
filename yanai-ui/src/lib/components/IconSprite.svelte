<!--
	Icon sprite — every symbol used by the app, defined once. Rendered a single
	time from +layout.svelte; <Icon /> references these by id.
-->
<svg xmlns="http://www.w3.org/2000/svg" style="display:none" aria-hidden="true">
	<symbol id="i-bell" viewBox="0 0 24 24">
		<path d="M10 5a2 2 0 1 1 4 0a7 7 0 0 1 4 6v3a4 4 0 0 0 2 3H4a4 4 0 0 0 2-3v-3a7 7 0 0 1 4-6" />
		<path d="M9 17v1a3 3 0 0 0 6 0v-1" />
	</symbol>
	<symbol id="i-logout" viewBox="0 0 24 24">
		<path d="M14 8V6a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h7a2 2 0 0 0 2-2v-2" />
		<path d="M9 12h12" />
		<path d="M18 15l3-3-3-3" />
	</symbol>
	<symbol id="i-search" viewBox="0 0 24 24">
		<circle cx="10" cy="10" r="7" />
		<path d="M21 21l-6-6" />
	</symbol>
	<symbol id="i-arrow-left" viewBox="0 0 24 24">
		<path d="M5 12h14" />
		<path d="M5 12l6 6" />
		<path d="M5 12l6-6" />
	</symbol>
	<symbol id="i-chevron-right" viewBox="0 0 24 24">
		<path d="M9 6l6 6-6 6" />
	</symbol>
	<symbol id="i-calculator" viewBox="0 0 24 24">
		<rect x="4" y="3" width="16" height="18" rx="2" />
		<rect x="8" y="7" width="8" height="3" />
		<path d="M8 14h.01" />
		<path d="M12 14h.01" />
		<path d="M16 14h.01" />
		<path d="M8 17h.01" />
		<path d="M12 17h.01" />
		<path d="M16 17h.01" />
	</symbol>
	<symbol id="i-book" viewBox="0 0 24 24">
		<path d="M19 4v16H7a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2z" />
		<path d="M9 8h6" />
	</symbol>
	<symbol id="i-bank" viewBox="0 0 24 24">
		<path d="M3 21h18" />
		<path d="M3 10h18" />
		<path d="M5 6l7-3 7 3" />
		<path d="M4 10v11" />
		<path d="M20 10v11" />
		<path d="M8 14v3" />
		<path d="M12 14v3" />
		<path d="M16 14v3" />
	</symbol>
	<symbol id="i-world" viewBox="0 0 24 24">
		<circle cx="12" cy="12" r="9" />
		<path d="M3.6 9h16.8" />
		<path d="M3.6 15h16.8" />
		<path d="M11.5 3a17 17 0 0 0 0 18" />
		<path d="M12.5 3a17 17 0 0 1 0 18" />
	</symbol>
	<symbol id="i-checklist" viewBox="0 0 24 24">
		<path d="M9.6 20H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2v6" />
		<path d="M14 19l2 2 4-4" />
		<path d="M9 8h4" />
		<path d="M9 12h2" />
	</symbol>
	<symbol id="i-clock" viewBox="0 0 24 24">
		<circle cx="12" cy="12" r="9" />
		<path d="M12 7v5l3 3" />
	</symbol>
	<symbol id="i-circle-check" viewBox="0 0 24 24">
		<circle cx="12" cy="12" r="9" />
		<path d="M9 12l2 2 4-4" />
	</symbol>
	<symbol id="i-flag" viewBox="0 0 24 24">
		<path d="M5 5a5 5 0 0 1 7 0a5 5 0 0 0 7 0v9a5 5 0 0 1-7 0a5 5 0 0 0-7 0z" />
		<path d="M5 21v-7" />
	</symbol>
	<symbol id="i-mic" viewBox="0 0 24 24">
		<rect x="9" y="2" width="6" height="11" rx="3" />
		<path d="M5 10a7 7 0 0 0 14 0" />
		<path d="M12 17v4" />
		<path d="M8 21h8" />
	</symbol>
	<symbol id="i-play" viewBox="0 0 24 24">
		<path d="M7 4v16l13-8z" fill="currentColor" stroke="none" />
	</symbol>
	<symbol id="i-pause" viewBox="0 0 24 24">
		<rect x="7" y="4" width="4" height="16" rx="1" fill="currentColor" stroke="none" />
		<rect x="13" y="4" width="4" height="16" rx="1" fill="currentColor" stroke="none" />
	</symbol>
	<symbol id="i-stop" viewBox="0 0 24 24">
		<rect x="6" y="6" width="12" height="12" rx="2" fill="currentColor" stroke="none" />
	</symbol>
	<symbol id="i-save" viewBox="0 0 24 24">
		<path d="M6 4h10l4 4v10a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2z" />
		<circle cx="12" cy="14" r="2" />
		<path d="M14 4v4H8V4" />
	</symbol>
	<symbol id="i-trash" viewBox="0 0 24 24">
		<path d="M4 7h16" />
		<path d="M10 11v6" />
		<path d="M14 11v6" />
		<path d="M5 7l1 12a2 2 0 0 0 2 2h8a2 2 0 0 0 2-2l1-12" />
		<path d="M9 7V4h6v3" />
	</symbol>
	<symbol id="i-sparkles" viewBox="0 0 24 24">
		<path d="M12 3l1.5 4.5L18 9l-4.5 1.5L12 15l-1.5-4.5L6 9l4.5-1.5z" />
		<path d="M18 15l.7 2.3L21 18l-2.3.7L18 21l-.7-2.3L15 18l2.3-.7z" />
	</symbol>
	<symbol id="i-plus" viewBox="0 0 24 24">
		<path d="M12 5v14" />
		<path d="M5 12h14" />
	</symbol>
	<symbol id="i-trending-down" viewBox="0 0 24 24">
		<path d="M3 7l6 6 4-4 8 8" />
		<path d="M21 10v7h-7" />
	</symbol>
	<symbol id="i-alert" viewBox="0 0 24 24">
		<path d="M12 9v4" />
		<path d="M10.2 4l-8.4 14A2 2 0 0 0 3.5 21h17a2 2 0 0 0 1.7-3l-8.4-14a2 2 0 0 0-3.4 0z" />
		<path d="M12 17h.01" />
	</symbol>
	<symbol id="i-clipboard-check" viewBox="0 0 24 24">
		<path d="M9 5H7a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V7a2 2 0 0 0-2-2h-2" />
		<rect x="9" y="3" width="6" height="4" rx="2" />
		<path d="M9 14l2 2 4-4" />
	</symbol>
	<symbol id="i-presentation" viewBox="0 0 24 24">
		<path d="M3 4h18" />
		<path d="M4 4v10a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1V4" />
		<path d="M12 16v4" />
		<path d="M9 20h6" />
	</symbol>
	<symbol id="i-users" viewBox="0 0 24 24">
		<circle cx="9" cy="8" r="3.5" />
		<path d="M3 20a6 6 0 0 1 12 0" />
		<path d="M16 5.2a3.5 3.5 0 0 1 0 5.6" />
		<path d="M18 14.3A6 6 0 0 1 21 20" />
	</symbol>
</svg>
