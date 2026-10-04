// AttemptReviewPage.tsx - Watch back every answer, with its transcript and score.
// Results appear live as the worker finishes each answer.
import { useAuth } from "react-oidc-context";
import { Link, useParams } from "react-router";
import { useApi } from "../api";
import { useAttemptUpdates } from "../hooks/useAttemptUpdates";
import type { AttemptDetail, AttemptQuestion, ProcessingStatus, VideoUrlResponse } from "../types";

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

// Each answer asks the backend for its own temporary playback link.
// The video then streams straight from S3 into the <video> player.
function AnswerVideo({ attemptId, order, token }: { attemptId: string; order: number; token?: string }) {
  const { data, error, loading } = useApi<VideoUrlResponse>(
    `/attempts/${attemptId}/questions/${order}/video-url`,
    token,
  );
  if (loading) return <p className="muted">Loading video...</p>;
  if (error || !data) return <p className="error">Couldn't load this video.</p>;
  return <video className="recorder-video" src={data.url} controls playsInline preload="metadata" />;
}

function Results({ question }: { question: AttemptQuestion }) {
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
      {question.evaluation ? (
        <>
          <div className="score">
            <strong>{question.evaluation.score}</strong>/100
            <div className="score-bar">
              <div style={{ width: `${question.evaluation.score}%` }} />
            </div>
          </div>
          <p>{question.evaluation.feedback}</p>
          {question.evaluation.covered_points.length > 0 && (
            <>
              <h3>What you covered</h3>
              <ul className="points covered">
                {question.evaluation.covered_points.map((point) => <li key={point}>{point}</li>)}
              </ul>
            </>
          )}
          {question.evaluation.missing_points.length > 0 && (
            <>
              <h3>What to add next time</h3>
              <ul className="points missing">
                {question.evaluation.missing_points.map((point) => <li key={point}>{point}</li>)}
              </ul>
            </>
          )}
        </>
      ) : (
        question.type === "situational" && (
          <p className="muted">Feedback on situational answers using the STAR method is coming soon.</p>
        )
      )}

      {/* <details> is a built-in collapsible section - no JavaScript needed. */}
      <details>
        <summary>Transcript</summary>
        <p className="transcript">{question.transcript || "(No speech was detected.)"}</p>
      </details>
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
          {question.answered ? (
            <>
              <AnswerVideo attemptId={attempt.attempt_id} order={question.order} token={token} />
              <Results question={question} />
            </>
          ) : (
            <p className="muted">Not answered yet.</p>
          )}
        </section>
      ))}
    </>
  );
}
