import type { Snippet } from 'svelte';
export type ButtonVariant = 'primary' | 'secondary';
export type ActionVariant = 'neutral' | 'main' | 'remove' | 'link';
export type NoticeVariant = 'info' | 'attention' | 'danger';
export type Status = 'done' | 'due' | 'waiting';
export type TextVariant =
	'display' | 'title' | 'heading' | 'body' | 'body-strong' | 'small' | 'caption' | 'label';
export interface Option {
	value: string;
	label: string;
	disabled?: boolean;
}
export interface CheckOption extends Option {
	description?: string;
}
export interface Capability {
	id: string;
	label: string;
	covered: boolean;
}
export interface StatusItem {
	id: string;
	name: string;
	status: Status;
	label: string;
	detail?: string;
}
export interface ToastMessage {
	id: string | number;
	message: string;
	actionLabel?: string;
	onaction?: () => void;
	durationMs?: number;
}
export interface ContentProps {
	children: Snippet;
	class?: string;
}
