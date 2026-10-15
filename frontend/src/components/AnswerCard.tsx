// AnswerCard.tsx - One shared answer, shown as a card that links to its page.
// Used on the Community page, both in the list and in search results.
import { Link } from "react-router";
import type { SharedAnswerSummary } from "../types";

export default function AnswerCard({ answer }: { answer: SharedAnswerSummary }) {
  return (
    <Link to={`/community/answers/${answer.answer_id}`} className="card answer-card">
      <p className="muted small">
        {answer.interview_title} &middot; Question {answer.question_order}
        {answer.score !== null && <> &middot; {answer.score}/100</>}
        {answer.is_mine && <span className="badge mine">your answer</span>}
      </p>
      <h3>{answer.question_text}</h3>
      {/* An excerpt only: the full transcript is on the answer's own page. */}
      <p>{answer.excerpt ? `"${answer.excerpt}..."` : "(No transcript yet.)"}</p>
    </Link>
  );
}
