// SharedAnswerPage.tsx - One shared answer in full: transcripts and feedback.
// There's deliberately no video here: shared answers never include it.
import { useAuth } from "react-oidc-context";
import { Link, useParams } from "react-router";
import { useApi } from "../api";
import type { SharedAnswerDetail } from "../types";

export default function SharedAnswerPage() {
  const { answerId } = useParams();
  const auth = useAuth();
  const { data: answer, error, loading } = useApi<SharedAnswerDetail>(
    `/community/answers/${answerId}`,
    auth.user?.access_token,
  );

  if (loading) return <p className="muted">Loading answer...</p>;
  if (error) return <p className="error">{error.message}</p>;
  if (!answer) return null;

  return (
    <>
      <Link to="/community" className="muted">
        &larr; Community answers
      </Link>
      <p className="muted">
        {answer.interview_title} &middot; Question {answer.question_order}
        {answer.is_mine && <span className="badge mine">your answer</span>}
      </p>
      <h1>
        <span className={`badge ${answer.question_type}`}>{answer.question_type}</span>
        {answer.question_text}
      </h1>

      <section className="card">
        <h2>Answer</h2>
        <p className="transcript">{answer.transcript || "(No transcript.)"}</p>
        {answer.follow_ups.map((followUp) => (
          <div key={followUp.number} className="follow-up-answer">
            <h3>
              <span className="badge follow-up">follow-up {followUp.number}</span>
              {followUp.question}
            </h3>
            <p className="transcript">{followUp.transcript || "(No transcript.)"}</p>
          </div>
        ))}
      </section>

      {answer.evaluation && (
        <section className="card">
          <h2>Feedback</h2>
          <p>
            <strong>{answer.evaluation.score}</strong>/100
          </p>
          <p>{answer.evaluation.feedback}</p>
        </section>
      )}
    </>
  );
}
