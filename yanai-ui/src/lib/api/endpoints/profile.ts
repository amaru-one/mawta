import { apiGet } from '../client';
import type { ProfileDto } from '../dto';

export function getProfile(termId?: string): Promise<ProfileDto> {
	const qs = termId ? `?term_id=${termId}` : '';
	return apiGet<ProfileDto>(`/profile${qs}`);
}
