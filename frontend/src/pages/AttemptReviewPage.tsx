// AttemptReviewPage.tsx - Watch back every answer in one attempt.
import { useAuth } from "react-oidc-context";
import { Link, useParams } from "react-router";
import { useApi } from "../api";
import type { AttemptDetail, VideoUrlResponse } from "../types";

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

export default function AttemptReviewPage() {
  const { attemptId } = useParams();
  const auth = useAuth();
  const token = auth.user?.access_token;
  const { data: attempt, error, loading } = useApi<AttemptDetail>(`/attempts/${attemptId}`, token);

  if (loading) return <p className="muted">Loading your answers...</p>;
  if (error) return <p className="error">{error.message}</p>;
  if (!attempt) return null;

  return (
    <>
      <Link to="/my-interviews" className="muted">
        &larr; My interviews
      </Link>
      <h1>{attempt.interview_title}: your answers</h1>
      <p className="muted">Transcripts and scores arrive in the next phases.</p>

      {attempt.questions.map((question) => (
        <section key={question.order} className="card answer">
          <h2>
            <span className={`badge ${question.type}`}>{question.type}</span>
            {question.order}. {question.text}
          </h2>
          {question.answered ? (
            <AnswerVideo attemptId={attempt.attempt_id} order={question.order} token={token} />
          ) : (
            <p className="muted">Not answered yet.</p>
          )}
        </section>
      ))}
    </>
  );
}
