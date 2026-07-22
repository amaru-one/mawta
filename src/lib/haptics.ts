// Optional haptic feedback — silently ignored where unsupported.

function vibrate(pattern: number | number[]): void {
	if (typeof navigator !== 'undefined' && 'vibrate' in navigator) {
		navigator.vibrate(pattern);
	}
}

export const hapticTap = (): void => vibrate(20);
export const hapticRecordStart = (): void => vibrate([10, 20, 10]);
export const hapticSuccess = (): void => vibrate(50);
