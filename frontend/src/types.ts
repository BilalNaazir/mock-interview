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
