// AttemptReviewPage.tsx - Watch back every answer, with transcripts and feedback.
// Results appear live as the worker finishes each answer.
import { useAuth } from "react-oidc-context";
import { Link, useParams } from "react-router";
import { useApi } from "../api";
import { useAttemptUpdates } from "../hooks/useAttemptUpdates";
import type {
  AttemptDetail,
  AttemptQuestion,
  KnowledgeEvaluation,
  ProcessingStatus,
  StarEvaluation,
  StarRating,
  VideoUrlResponse,
} from "../types";

const STATUS_LABELS: Record<ProcessingStatus, string> = {
  queued: "Waiting in line...",
  transcribing: "Transcribing your answer...",
  scoring: "Scoring your answer...",
  done: "Done",
  failed: "Processing failed",
  not_configured: "Not processed (processing is switched off)",
};

// Statuses where the worker is still busy - while any answer is in one of
// these, we keep the WebSocket open to hear when it finishes.
const IN_PROGRESS: (ProcessingStatus | null)[] = ["queued", "transcribing", "scoring"];

const STAR_LABELS = { situation: "Situation", task: "Task", action: "Action", result: "Result" } as const;
const RATING_LABELS: Record<StarRating, string> = { clear: "Clear", partial: "Partly there", missing: "Missing" };

// Asks the backend for a temporary playback link for one recording (the main
// answer if no recordingId is given). The video then streams straight from S3.
function AnswerVideo(props: { attemptId: string; order: number; recordingId?: string | null; token?: string }) {
  const query = props.recordingId ? `?recording_id=${props.recordingId}` : "";
  const { data, error, loading } = useApi<VideoUrlResponse>(
    `/attempts/${props.attemptId}/questions/${props.order}/video-url${query}`,
    props.token,
  );
  if (loading) return <p className="muted">Loading video...</p>;
  if (error || !data) return <p className="error">Couldn't load this video.</p>;
  return <video className="recorder-video" src={data.url} controls playsInline preload="metadata" />;
}

function ScoreBar({ score }: { score: number }) {
  return (
    <div className="score">
      <strong>{score}</strong>/100
      <div className="score-bar">
        <div style={{ width: `${score}%` }} />
      </div>
    </div>
  );
}

function KnowledgeResults({ evaluation }: { evaluation: KnowledgeEvaluation }) {
  return (
    <>
      <ScoreBar score={evaluation.score} />
      <p>{evaluation.feedback}</p>
      {evaluation.covered_points.length > 0 && (
        <>
          <h3>What you covered</h3>
          <ul className="points covered">
            {evaluation.covered_points.map((point) => <li key={point}>{point}</li>)}
          </ul>
        </>
      )}
      {evaluation.missing_points.length > 0 && (
        <>
          <h3>What to add next time</h3>
          <ul className="points missing">
            {evaluation.missing_points.map((point) => <li key={point}>{point}</li>)}
          </ul>
        </>
      )}
    </>
  );
}

function StarResults({ evaluation }: { evaluation: StarEvaluation }) {
  return (
    <>
      <ScoreBar score={evaluation.score} />
      <p>{evaluation.feedback}</p>
      <div className="star-grid">
        {(Object.keys(STAR_LABELS) as (keyof typeof STAR_LABELS)[]).map((element) => (
          <div key={element} className={`star-cell ${evaluation[element].rating}`}>
            <strong>{STAR_LABELS[element]}</strong>
            <span className="star-rating">{RATING_LABELS[evaluation[element].rating]}</span>
            <span className="muted">{evaluation[element].comment}</span>
          </div>
        ))}
      </div>
    </>
  );
}

function Results({ question, attemptId, token }: { question: AttemptQuestion; attemptId: string; token?: string }) {
  const status = question.processing_status;
  if (!status) return null;

  if (status !== "done") {
    return (
      <p className={status === "failed" ? "error" : "muted"}>
        {IN_PROGRESS.includes(status) && <span className="spinner" aria-hidden="true" />}
        {STATUS_LABELS[status]}
      </p>
    );
  }

  return (
    <div className="results">
      {/* Checking `kind` tells TypeScript which kind of evaluation this is. */}
      {question.evaluation?.kind === "knowledge" && <KnowledgeResults evaluation={question.evaluation} />}
      {question.evaluation?.kind === "star" && <StarResults evaluation={question.evaluation} />}

      {/* <details> is a built-in collapsible section - no JavaScript needed. */}
      <details>
        <summary>Transcript</summary>
        <p className="transcript">{question.transcript || "(No speech was detected.)"}</p>
      </details>

      {question.follow_ups.filter((f) => f.answered).map((followUp) => (
        <div key={followUp.number} className="follow-up-answer">
          <h3>
            <span className="badge follow-up">follow-up {followUp.number}</span>
            {followUp.question}
          </h3>
          <AnswerVideo attemptId={attemptId} order={question.order} recordingId={followUp.recording_id} token={token} />
          <details>
            <summary>Transcript</summary>
            <p className="transcript">{followUp.transcript || "(No speech was detected.)"}</p>
          </details>
        </div>
      ))}
    </div>
  );
}

export default function AttemptReviewPage() {
  const { attemptId } = useParams();
  const auth = useAuth();
  const token = auth.user?.access_token;
  const { data: attempt, error, loading, reload } = useApi<AttemptDetail>(`/attempts/${attemptId}`, token);

  // Only keep a live connection while something is still being processed.
  const anythingInProgress = attempt?.questions.some((q) => IN_PROGRESS.includes(q.processing_status)) ?? false;
  useAttemptUpdates(attemptId, token, reload, anythingInProgress);

  // As before: show "Loading" only the first time, not on every live reload.
  if (loading && !attempt) return <p className="muted">Loading your answers...</p>;
  if (error) return <p className="error">{error.message}</p>;
  if (!attempt) return null;

  return (
    <>
      <Link to="/my-interviews" className="muted">
        &larr; My interviews
      </Link>
      <h1>{attempt.interview_title}: your answers</h1>
      {anythingInProgress && (
        <p className="muted">Your answers are being processed. Results appear here as soon as they're ready.</p>
      )}

      {attempt.questions.map((question) => (
        <section key={question.order} className="card answer">
          <h2>
            <span className={`badge ${question.type}`}>{question.type}</span>
            {question.order}. {question.text}
          </h2>
          {question.recording_id ? (
            <>
              <AnswerVideo attemptId={attempt.attempt_id} order={question.order} token={token} />
              <Results question={question} attemptId={attempt.attempt_id} token={token} />
            </>
          ) : (
            <p className="muted">Not answered yet.</p>
          )}
        </section>
      ))}
    </>
  );
}
