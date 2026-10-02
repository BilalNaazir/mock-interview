// HomePage.tsx - Lists the five interviews. Works without logging in.
import { Link } from "react-router";
import { useApi } from "../api";
import type { InterviewSummary } from "../types";

export default function HomePage() {
  const { data: interviews, error, loading } = useApi<InterviewSummary[]>("/interviews");

  if (loading) return <p className="muted">Loading interviews...</p>;
  if (error) return <p className="error">Couldn't load interviews: {error.message}</p>;

  return (
    <>
      <h1>Choose an interview</h1>
      <p className="muted">
        Each interview has 3 knowledge questions and 2 situational questions, answered on camera.
      </p>

      <div className="grid">
        {interviews?.map((interview) => (
          <div key={interview.slug} className="card">
            <h2>{interview.title}</h2>
            <p>{interview.description}</p>
            <p className="muted">{interview.question_count} questions</p>
            {/* Clicking this when logged out: RequireAuth sends you to log in,
                then brings you straight back to this interview. */}
            <Link to={`/interviews/${interview.slug}`} className="button">
              Start
            </Link>
          </div>
        ))}
      </div>
    </>
  );
}
