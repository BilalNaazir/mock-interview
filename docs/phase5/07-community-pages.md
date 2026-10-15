# 07 The Community pages

Two new pages: **Community** (`/community`), to browse and search shared answers, and the **shared answer** page (`/community/answers/:answerId`), to read one in full. Both are login-only.

---

## `frontend/src/types.ts`: the shapes from the backend

**Where and when it's used:** by the pages below, so TypeScript can check every field they use.

```typescript
export interface SharedAnswerSummary {
  answer_id: string;
  interview_slug: string;
  interview_title: string;
  question_order: number;
  question_type: QuestionType;
  question_text: string;
  excerpt: string;
  score: number | null;
  is_mine: boolean;
}
```

- Matches `SharedAnswerSummary` in `models.py` (chapter 06). `number | null` means "a number, or nothing".

```typescript
export interface SharedAnswerDetail extends SharedAnswerSummary {
  transcript: string | null;
  follow_ups: { number: number; question: string; transcript: string | null }[];
  evaluation: Evaluation | null;
}
```

- `extends SharedAnswerSummary` means "everything a summary has, plus these". That mirrors the backend, where the detail is built from `to_summary` plus extra fields.
- `{ ... }[]` is a list of objects with that shape, written inline rather than as a separate named type.

```typescript
export interface SearchResponse {
  reply: string;
  answers: SharedAnswerSummary[];
}
```

- The agent's reply and its chosen answers.

---

## `frontend/src/components/AnswerCard.tsx`

**Where and when it's used:** the Community page uses it for every answer, both in the browse list and in search results.

```typescript
import { Link } from "react-router";
import type { SharedAnswerSummary } from "../types";
```

- `Link` makes a clickable link that changes page without reloading the whole app.

```tsx
export default function AnswerCard({ answer }: { answer: SharedAnswerSummary }) {
  return (
    <Link to={`/community/answers/${answer.answer_id}`} className="card answer-card">
```

- The whole card is one link to the answer's page. The type `{ answer: SharedAnswerSummary }` is written inline, since there's only one prop.

```tsx
      <p className="muted small">
        {answer.interview_title} &middot; Question {answer.question_order}
        {answer.score !== null && <> &middot; {answer.score}/100</>}
        {answer.is_mine && <span className="badge mine">your answer</span>}
      </p>
```

- A small line like "Agentic AI · Question 3 · 80/100".
- `{condition && <...>}` shows something only when the condition is true. The score is shown only if it exists (`!== null`), and the "your answer" badge only on your own.
- `<> ... </>` is a **fragment**: a way to group several pieces without adding an extra element to the page.
- `&middot;` is the HTML code for the dot character "·".

```tsx
      <h3>{answer.question_text}</h3>
      <p>{answer.excerpt ? `"${answer.excerpt}..."` : "(No transcript yet.)"}</p>
    </Link>
  );
}
```

- The question, then the excerpt in quotes, or a placeholder if there's no transcript. `condition ? A : B` shows A if the condition is true, otherwise B.

---

## `frontend/src/pages/CommunityPage.tsx`

**Where and when it's used:** the page at `/community`, reached from the **Community** link in the header.

### Imports

```typescript
import { useState, type FormEvent } from "react";
import { useAuth } from "react-oidc-context";
import { apiPost, useApi } from "../api";
import AnswerCard from "../components/AnswerCard";
import type { InterviewSummary, SearchResponse, SharedAnswerSummary } from "../types";
```

- `FormEvent` is the type of a form's submit event. `type` before it means it's only used for type-checking.
- `useAuth` gives the login token, `apiPost` sends the search, and `useApi` loads lists.

### The "Ask" box

```typescript
function AskBox({ token }: { token?: string }) {
```

- A component used only on this page, so it lives in the same file.

```typescript
  const [question, setQuestion] = useState("");
  const [result, setResult] = useState<SearchResponse | null>(null);
  const [searching, setSearching] = useState(false);
  const [error, setError] = useState<string | null>(null);
```

- Four pieces of state: what's typed in the box, the latest search result, whether a search is running, and an error message.

```typescript
  async function ask(event: FormEvent) {
    event.preventDefault();
```

- Runs when the form is submitted, by clicking **Ask** or pressing Enter. `preventDefault()` stops the browser's old-fashioned behaviour of reloading the whole page on form submit.

```typescript
    setSearching(true);
    setError(null);
    try {
      setResult(await apiPost<SearchResponse>("/community/search", token, { question }));
```

- Marks a search as running, clears old errors, sends the question to `POST /community/search`, and stores the result when it arrives. This can take several seconds, since the agent may call Claude a few times.

```typescript
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSearching(false);
    }
  }
```

- Shows the backend's message if it fails, for example the 429 "limit reached" message, or 503 when search is switched off.

```tsx
  return (
    <section className="card ask">
      <h2>Ask about shared answers</h2>
      <form onSubmit={ask} className="ask-form">
```

- `onSubmit={ask}` connects the form to the function above.

```tsx
        <input
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          placeholder='e.g. "Which answers to question 3 talked about observing a RAG pipeline using LangSmith?"'
          maxLength={500}
        />
```

- A **controlled input**: React holds its value in `question` (`value={question}`), and every keystroke updates it (`onChange`).
- The placeholder shows an example question, faded, until something is typed.
- `maxLength={500}` matches the backend's limit, so the browser stops typing at 500 characters. The backend still checks too, since browser limits can be bypassed.

```tsx
        <button className="button" disabled={searching || question.trim().length < 3}>
          {searching ? "Searching..." : "Ask"}
        </button>
      </form>
```

- The button is disabled while searching, or when the question is shorter than 3 characters (matching the backend's minimum). `trim()` removes spaces at the start and end, so a question of just spaces doesn't count.
- Its label changes to "Searching..." while it waits.

```tsx
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
```

- Shows any error, and once there's a result, the agent's reply and a card for each answer it chose.
- `.map(...)` turns each answer into a card. `key` gives React a unique ID per card, so it can update the list efficiently.

### The page

```typescript
export default function CommunityPage() {
  const auth = useAuth();
  const token = auth.user?.access_token;
  const [interviewSlug, setInterviewSlug] = useState("");
  const [questionOrder, setQuestionOrder] = useState("");
```

- The login token, and the two filter choices. An empty string means "all".

```typescript
  const params = new URLSearchParams();
  if (interviewSlug) params.set("interview_slug", interviewSlug);
  if (questionOrder) params.set("question_order", questionOrder);
```

- `URLSearchParams` builds a query string like `interview_slug=agentic-ai&question_order=3`, adding only the filters that are chosen and escaping any special characters safely.

```typescript
  const { data: interviews } = useApi<InterviewSummary[]>("/interviews");
  const { data: answers, error, loading } = useApi<SharedAnswerSummary[]>(`/community/answers?${params}`, token);
```

- Loads the five interviews, for the dropdown (the same public endpoint as the home page).
- Loads the shared answers with the current filters. Putting `params` into the path means that whenever a filter changes, the path changes, and `useApi` (from Phase 2) loads again automatically.

```tsx
  return (
    <>
      <h1>Community answers</h1>
      <p className="muted">Answers other candidates chose to share: transcripts and feedback, without names or videos.</p>

      <AskBox token={token} />
```

- The heading, a reminder of what's shared, then the Ask box.

```tsx
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
```

- A dropdown of interviews. Picking one sets `interviewSlug`, which changes `params`, which reloads the list.
- `interviews?.map(...)`: the `?.` means "only if `interviews` has loaded", so the page doesn't crash before then.

```tsx
        <select value={questionOrder} onChange={(event) => setQuestionOrder(event.target.value)}>
          <option value="">All questions</option>
          {[1, 2, 3, 4, 5].map((order) => (
            <option key={order} value={order}>
              Question {order}
            </option>
          ))}
        </select>
      </div>
```

- A dropdown for question numbers 1 to 5, made by mapping over the list `[1, 2, 3, 4, 5]`.

```tsx
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
```

- The usual three states (loading, error, success), plus a friendly message when nothing matches, then a card per answer.

---

## `frontend/src/pages/SharedAnswerPage.tsx`

**Where and when it's used:** the page at `/community/answers/:answerId`, opened by clicking an answer card.

```typescript
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
```

- `useParams()` reads the `:answerId` part of the address. Then the answer is loaded from `GET /community/answers/{answerId}`.

```tsx
  if (loading) return <p className="muted">Loading answer...</p>;
  if (error) return <p className="error">{error.message}</p>;
  if (!answer) return null;
```

- The usual early returns. A private or missing answer shows the backend's "Shared answer not found" message.

```tsx
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
```

- A link back (`&larr;` is "←"), which interview and question this is, and the question as the heading, with the same knowledge/situational badge used elsewhere.

```tsx
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
```

- The main transcript, then each follow-up question and its answer, reusing the Phase 4 styles.
- `a || b` shows `b` if `a` is empty or missing.
- There's deliberately **no video player**: shared answers never include the video.

```tsx
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
```

- If the answer has been scored, its score and feedback. Both kinds of evaluation (knowledge and STAR) have `score` and `feedback`, so TypeScript allows these two fields without checking `kind` first.

---

## `frontend/src/App.tsx`: the routes

```typescript
import CommunityPage from "./pages/CommunityPage";
import SharedAnswerPage from "./pages/SharedAnswerPage";
```

```tsx
          <Route path="/community" element={<RequireAuth><CommunityPage /></RequireAuth>} />
          <Route path="/community/answers/:answerId" element={<RequireAuth><SharedAnswerPage /></RequireAuth>} />
```

- Two new routes, both wrapped in `RequireAuth`, so logged-out visitors are sent to log in first. `:answerId` is a placeholder that `useParams()` reads.

---

## `frontend/src/components/Header.tsx`

```tsx
            <Link to="/community">Community</Link>
```

- A link next to **My interviews**, shown only when logged in, because it sits inside the same logged-in part of the header.

---

## `frontend/src/index.css`: the new styles

```css
.small { font-size: 0.85rem; }
```

- Smaller text, for the card's info line and the sharing explanation.

```css
.share-toggle { margin-top: 16px; padding-top: 12px; border-top: 1px solid var(--border); }
.share-toggle .checkbox { margin: 0; }
.share-toggle p { margin: 4px 0 0; }
```

- Separates the share checkbox from the results above it with a thin line. `var(--border)` uses the border colour defined once at the top of the file, which also switches automatically in dark mode.

```css
.share-all { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-bottom: 16px; }
```

- Lays out the "Share all" row in a line (`flex`), vertically centred, with gaps, wrapping onto a new line on narrow screens.

```css
.ask { margin-bottom: 24px; }
.ask-form { display: flex; gap: 8px; flex-wrap: wrap; }
.ask-form input, .filters select {
  flex: 1; min-width: 220px; padding: 8px 10px; font: inherit; color: var(--text);
  background: var(--surface); border: 1px solid var(--border); border-radius: 6px;
}
```

- The Ask form puts the input and button side by side. The input and dropdowns share a style: `flex: 1` lets them stretch to fill the space, but never narrower than 220px (on a phone they wrap instead). `font: inherit` makes them use the page's font rather than the browser's default.

```css
.reply { font-size: 1.05rem; margin: 16px 0; }
.filters { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 16px; }
```

- Slightly larger text for the agent's reply, and the filter dropdowns side by side.

```css
.answer-card { display: block; color: var(--text); text-decoration: none; }
.answer-card:hover { border-color: var(--accent); }
.answer-card h3 { margin: 4px 0 8px; font-size: 1rem; }
.answer-card p { margin: 0; }
```

- Cards are links, so these remove the link's usual blue colour and underline, and make the whole card a block. `:hover` highlights the border when the mouse is over a card, showing it's clickable.

```css
.badge.mine { margin-left: 8px; border-color: var(--accent); color: var(--accent); }
```

- The "your answer" badge, in the accent colour.
