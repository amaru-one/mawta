import { apiGet } from '../client';
import type { ClassSearchDto, HomeDto, MeDto } from '../dto';

export function getMe(): Promise<MeDto> {
	return apiGet<MeDto>('/me');
}

// date defaults to today in the tenant's timezone when omitted.
export function getHome(date?: string): Promise<HomeDto> {
	return apiGet<HomeDto>(date ? `/home?date=${date}` : '/home');
}

export function searchClasses(q: string): Promise<ClassSearchDto> {
	return apiGet<ClassSearchDto>(`/classes?q=${encodeURIComponent(q)}`);
}
