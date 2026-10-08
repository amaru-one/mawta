import { apiSend } from '../client';
import type { ScoreCorrectDto, ScoreCreateDto } from '../dto';

export function createScore(assessmentId: string, body: ScoreCreateDto): Promise<{ id: string }> {
	return apiSend<{ id: string }>('POST', `/assessments/${assessmentId}/scores`, body);
}

// Scores are append-only server-side: corrections supersede the old row.
// A second correct on the same id fails with 409 already_superseded.
export function correctScore(scoreId: string, body: ScoreCorrectDto): Promise<{ id: string }> {
	return apiSend<{ id: string }>('POST', `/scores/${scoreId}/correct`, body);
}
