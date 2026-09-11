import { apiSend } from '../client';
import type { MeDto } from '../dto';

export function login(username: string, password: string): Promise<MeDto> {
	return apiSend<MeDto>('POST', '/auth/login', { username, password });
}

export function logout(): Promise<void> {
	return apiSend<void>('POST', '/auth/logout');
}
