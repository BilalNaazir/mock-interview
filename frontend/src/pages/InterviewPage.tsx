// InterviewPage.tsx - Shows one interview's questions (login required).
// In Phase 2 this becomes the real interview screen, with webcam recording.
import { useAuth } from "react-oidc-context";
import { Link, useParams } from "react-router";
import { useApi } from "../api";
import type { InterviewDetail } from "../types";

export default function InterviewPage() {
  const { slug } = useParams();   // the ":slug" part of the URL
  const auth = useAuth();
  const { data: interview, error, loading } = useApi<InterviewDetail>(
    `/interviews/${slug}`,
    auth.user?.access_token,
  );

  if (loading) return <p className="muted">Loading interview...</p>;
  if (error) return <p className="error">{error.message}</p>;
  if (!interview) return null;

  return (
    <>
      <Link to="/" className="muted">
        &larr; All interviews
      </Link>
      <h1>{interview.title}</h1>
      <p>{interview.description}</p>

      <ol className="questions">
        {interview.questions.map((question) => (
          <li key={question.order}>
            <span className={`badge ${question.type}`}>{question.type}</span>
            {question.text}
          </li>
        ))}
      </ol>

      <p className="muted">Recording answers arrives in Phase 2.</p>
    </>
  );
}
