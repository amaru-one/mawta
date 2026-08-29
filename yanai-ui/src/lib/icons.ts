// Names of the symbols defined in IconSprite.svelte. Keep the two in sync —
// <Icon name="…" /> resolves to `#i-${name}` in that sprite.

export const ICON_NAMES = [
	'bell',
	'logout',
	'search',
	'arrow-left',
	'chevron-right',
	'calculator',
	'book',
	'bank',
	'world',
	'checklist',
	'circle-check',
	'flag',
	'mic',
	'play',
	'pause',
	'save',
	'trash',
	'sparkles',
	'plus',
	'trending-down',
	'alert',
	'clipboard-check',
	'presentation',
] as const;

export type IconName = (typeof ICON_NAMES)[number];
