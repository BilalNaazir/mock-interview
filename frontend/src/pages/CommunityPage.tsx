// CommunityPage.tsx - Browse and search answers other candidates have shared.
//
// Two ways to find answers:
//   1. Filters (interview + question number): an ordinary database query.
//   2. "Ask": a question in plain English, answered by the search agent,
//      which uses vector search to find answers by MEANING.
import { useState, type FormEvent } from "react";
import { useAuth } from "react-oidc-context";
import { apiPost, useApi } from "../api";
import AnswerCard from "../components/AnswerCard";
import type { InterviewSummary, SearchResponse, SharedAnswerSummary } from "../types";

function AskBox({ token }: { token?: string }) {
  const [question, setQuestion] = useState("");
  const [result, setResult] = useState<SearchResponse | null>(null);
  const [searching, setSearching] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function ask(event: FormEvent) {
    event.preventDefault(); // stop the browser reloading the page on submit
    setSearching(true);
    setError(null);
    try {
      setResult(await apiPost<SearchResponse>("/community/search", token, { question }));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSearching(false);
    }
  }

  return (
    <section className="card ask">
      <h2>Ask about shared answers</h2>
      <form onSubmit={ask} className="ask-form">
        <input
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          placeholder='e.g. "Which answers to question 3 talked about observing a RAG pipeline using LangSmith?"'
          maxLength={500}
        />
        <button className="button" disabled={searching || question.trim().length < 3}>
          {searching ? "Searching..." : "Ask"}
        </button>
      </form>
      {error && <p className="error">{error}</p>}
      {result && (
        <>
          <p className="reply">{result.reply}</p>
          <div className="grid">
            {result.answers.map((answer) => (
              <AnswerCard key={answer.answer_id} answer={answer} />
            ))}
          </div>
        </>
      )}
    </section>
  );
}

export default function CommunityPage() {
  const auth = useAuth();
  const token = auth.user?.access_token;
  const [interviewSlug, setInterviewSlug] = useState("");
  const [questionOrder, setQuestionOrder] = useState("");

  // URLSearchParams builds "?interview_slug=...&question_order=..." safely,
  // leaving out filters that aren't set.
  const params = new URLSearchParams();
  if (interviewSlug) params.set("interview_slug", interviewSlug);
  if (questionOrder) params.set("question_order", questionOrder);

  const { data: interviews } = useApi<InterviewSummary[]>("/interviews");
  const { data: answers, error, loading } = useApi<SharedAnswerSummary[]>(`/community/answers?${params}`, token);

  return (
    <>
      <h1>Community answers</h1>
      <p className="muted">Answers other candidates chose to share: transcripts and feedback, without names or videos.</p>

      <AskBox token={token} />

      <h2>Browse</h2>
      <div className="filters">
        <select value={interviewSlug} onChange={(event) => setInterviewSlug(event.target.value)}>
          <option value="">All interviews</option>
          {interviews?.map((interview) => (
            <option key={interview.slug} value={interview.slug}>
              {interview.title}
            </option>
          ))}
        </select>
        <select value={questionOrder} onChange={(event) => setQuestionOrder(event.target.value)}>
          <option value="">All questions</option>
          {[1, 2, 3, 4, 5].map((order) => (
            <option key={order} value={order}>
              Question {order}
            </option>
          ))}
        </select>
      </div>

      {loading && <p className="muted">Loading answers...</p>}
      {error && <p className="error">{error.message}</p>}
      {answers?.length === 0 && <p className="muted">No shared answers match yet.</p>}
      <div className="grid">
        {answers?.map((answer) => (
          <AnswerCard key={answer.answer_id} answer={answer} />
        ))}
      </div>
    </>
  );
}
