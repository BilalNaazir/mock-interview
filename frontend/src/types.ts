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

// Phase 3: where an answer is in the processing pipeline.
export type ProcessingStatus = "queued" | "transcribing" | "scoring" | "done" | "failed" | "not_configured";

// An evaluation is EITHER a knowledge one OR a STAR one. The "kind" field
// tells TypeScript which: after checking `evaluation.kind === "star"`, it
// knows the STAR fields exist (this is called "narrowing").
export interface KnowledgeEvaluation {
  kind: "knowledge";
  score: number; // 0-100
  covered_points: string[];
  missing_points: string[];
  feedback: string;
}

export type StarRating = "clear" | "partial" | "missing";

export interface StarElement {
  rating: StarRating;
  comment: string;
}

export interface StarEvaluation {
  kind: "star";
  score: number; // 0-100, worked out from the four ratings
  feedback: string;
  situation: StarElement;
  task: StarElement;
  action: StarElement;
  result: StarElement;
}

export type Evaluation = KnowledgeEvaluation | StarEvaluation;

export interface FollowUp {
  number: number;
  question: string;
  answered: boolean;
  recording_id: string | null;
  transcript: string | null;
}

// Phase 5: who can see an answer.
export type Visibility = "private" | "shared";

export interface AttemptQuestion extends Question {
  answered: boolean;
  processing_status: ProcessingStatus | null;
  transcript: string | null;
  recording_id: string | null;
  evaluation: Evaluation | null;
  follow_ups: FollowUp[];
  visibility: Visibility;
}

export interface RecordingLimits {
  max_recording_seconds: number;
  max_upload_bytes: number;
  allowed_content_types: string[];
  max_follow_ups: number;
}

// What the interview screen should show right now.
export type CurrentStep = "record_answer" | "evaluating" | "record_follow_up" | "finished";

export interface AttemptDetail {
  attempt_id: string;
  interview_slug: string;
  interview_title: string;
  status: AttemptStatus;
  current_question: number;
  current_step: CurrentStep;
  pending_follow_up: { number: number; question: string } | null;
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
  kind: "main" | "follow_up";
  follow_up_number: number | null;
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

// --- Phase 5: the Community pages -----------------------------------------
// These mirror the models in backend/app/models.py. Notice there's no field
// for anyone's name or video: the backend never sends them.

export interface VisibilityResponse {
  visibility: Visibility;
  changed: number;
}

export interface SharedAnswerSummary {
  answer_id: string;
  interview_slug: string;
  interview_title: string;
  question_order: number;
  question_type: QuestionType;
  question_text: string;
  excerpt: string;
  score: number | null;
  is_mine: boolean;
}

export interface SharedAnswerDetail extends SharedAnswerSummary {
  transcript: string | null;
  follow_ups: { number: number; question: string; transcript: string | null }[];
  evaluation: Evaluation | null;
}

export interface SearchResponse {
  reply: string;
  answers: SharedAnswerSummary[];
}
