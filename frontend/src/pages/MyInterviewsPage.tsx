// MyInterviewsPage.tsx - Every interview attempt the logged-in user has made.
import { useAuth } from "react-oidc-context";
import { Link } from "react-router";
import { useApi } from "../api";
import type { AttemptSummary } from "../types";

export default function MyInterviewsPage() {
  const auth = useAuth();
  const { data: attempts, error, loading } = useApi<AttemptSummary[]>("/attempts", auth.user?.access_token);

  if (loading) return <p className="muted">Loading your interviews...</p>;
  if (error) return <p className="error">{error.message}</p>;

  return (
    <>
      <h1>My interviews</h1>
      {attempts?.length === 0 && (
        <p className="muted">
          You haven't taken any interviews yet. <Link to="/">Choose one to start.</Link>
        </p>
      )}

      <div className="grid">
        {attempts?.map((attempt) => (
          <div key={attempt.attempt_id} className="card">
            <h2>{attempt.interview_title}</h2>
            <p className="muted">
              Started {new Date(attempt.started_at).toLocaleString()} &middot; {attempt.answered_count} of{" "}
              {attempt.question_count} answered
            </p>
            {attempt.status === "completed" ? (
              <Link className="button" to={`/attempts/${attempt.attempt_id}/review`}>
                Watch answers
              </Link>
            ) : (
              <Link className="button" to={`/attempts/${attempt.attempt_id}`}>
                Continue
              </Link>
            )}
          </div>
        ))}
      </div>
    </>
  );
}
