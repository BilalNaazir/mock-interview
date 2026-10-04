// types.ts - TypeScript descriptions of the data our API returns.
// These mirror the Pydantic models in backend/app/models.py. If the backend
// changes a field, update both, and TypeScript will point out every place
// in the frontend that needs fixing.

export type QuestionType = "knowledge" | "situational";

export interface Question {
  order: number;
  type: QuestionType;
  text: string;
}

export interface InterviewSummary {
  slug: string;
  title: string;
  description: string;
  question_count: number;
}

export interface InterviewDetail {
  slug: string;
  title: string;
  description: string;
  questions: Question[];
}

export interface UserProfile {
  email: string;
  name: string;
  share_answers_by_default: boolean;
}

// --- Phase 2: taking an interview ---------------------------------------

export type AttemptStatus = "in_progress" | "completed";

export interface StartAttemptResponse {
  attempt_id: string;
  resumed: boolean;
}

export interface AttemptQuestion extends Question {
  answered: boolean;
}

export interface RecordingLimits {
  max_recording_seconds: number;
  max_upload_bytes: number;
  allowed_content_types: string[];
}

export interface AttemptDetail {
  attempt_id: string;
  interview_slug: string;
  interview_title: string;
  status: AttemptStatus;
  current_question: number;
  questions: AttemptQuestion[];
  limits: RecordingLimits;
}

export interface AttemptSummary {
  attempt_id: string;
  interview_slug: string;
  interview_title: string;
  status: AttemptStatus;
  answered_count: number;
  question_count: number;
  started_at: string; // dates arrive as text in JSON
}

export interface UploadUrlResponse {
  recording_id: string;
  upload_url: string;
  upload_headers: Record<string, string>;
  expires_in_seconds: number;
}

export interface CompleteRecordingResponse {
  status: AttemptStatus;
  current_question: number;
}

export interface VideoUrlResponse {
  url: string;
  content_type: string;
  expires_in_seconds: number;
}
