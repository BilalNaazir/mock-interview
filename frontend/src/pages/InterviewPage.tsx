// InterviewPage.tsx - The introduction to one interview (login required).
// Shows the questions, asks for consent to record, then starts the attempt.
import { useState } from "react";
import { useAuth } from "react-oidc-context";
import { Link, useNavigate, useParams } from "react-router";
import { apiPost, useApi } from "../api";
import type { InterviewDetail, StartAttemptResponse } from "../types";

export default function InterviewPage() {
  const { slug } = useParams(); // the ":slug" part of the URL
  const auth = useAuth();
  const token = auth.user?.access_token;
  const navigate = useNavigate();
  const { data: interview, error, loading } = useApi<InterviewDetail>(`/interviews/${slug}`, token);

  const [consent, setConsent] = useState(false);
  const [starting, setStarting] = useState(false);
  const [startError, setStartError] = useState<string | null>(null);

  async function startInterview() {
    setStarting(true);
    setStartError(null);
    try {
      const result = await apiPost<StartAttemptResponse>("/attempts", token, {
        interview_slug: slug,
        consent_to_recording: consent,
      });
      // If an unfinished attempt existed, the backend returns that one, so
      // this either starts fresh or carries on where they left off.
      navigate(`/attempts/${result.attempt_id}`);
    } catch (err) {
      setStartError((err as Error).message);
      setStarting(false);
    }
  }

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

      <div className="card">
        <h2>Before you start</h2>
        <p>
          You'll answer one question at a time on camera. Each answer can be up to 3 minutes, and you can
          watch it back and re-record before submitting. Your recordings are stored privately, and only you
          can see them.
        </p>
        {/* Consent must be an active choice, so the box starts unticked. */}
        <label className="checkbox">
          <input type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)} />
          I agree to my camera and microphone being recorded, and the videos being stored for this interview.
        </label>
        {startError && <p className="error">{startError}</p>}
        <button className="button" onClick={startInterview} disabled={!consent || starting}>
          {starting ? "Starting..." : "Start interview"}
        </button>
      </div>
    </>
  );
}
