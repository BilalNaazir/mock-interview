// AttemptPage.tsx - The interview itself: one question at a time.
//
// The backend tells us what to show through `current_step`:
//   record_answer     -> the question, and the recorder
//   evaluating        -> "Reviewing your answer..." while the worker checks
//                        a situational answer against STAR (Phase 4)
//   record_follow_up  -> a follow-up question, and the recorder again
//   finished          -> all done
//
// For each recording, submitting runs three steps:
//   1. Ask OUR backend for a presigned upload URL
//   2. Upload the video STRAIGHT TO S3 with that URL (with a progress bar)
//   3. Tell our backend the upload finished, so it can check and move on
import { useState } from "react";
import { useAuth } from "react-oidc-context";
import { Link, useNavigate, useParams } from "react-router";
import { apiPost, uploadToS3, useApi } from "../api";
import VideoRecorder from "../components/VideoRecorder";
import { useAttemptUpdates } from "../hooks/useAttemptUpdates";
import type { AttemptDetail, CompleteRecordingResponse, ProcessingStatus, UploadUrlResponse } from "../types";

const WAITING_LABELS: Partial<Record<ProcessingStatus, string>> = {
  queued: "Getting ready to review your answer...",
  transcribing: "Listening to your answer...",
  scoring: "Checking your answer against STAR...",
};

export default function AttemptPage() {
  const { attemptId } = useParams();
  const auth = useAuth();
  const token = auth.user?.access_token;
  const navigate = useNavigate();
  const { data: attempt, error, loading, reload } = useApi<AttemptDetail>(`/attempts/${attemptId}`, token);

  const [uploadPercent, setUploadPercent] = useState<number | null>(null);
  const [submitError, setSubmitError] = useState<string | null>(null);

  // While a situational answer is being checked, listen for the worker's
  // decision: a follow-up question, or "accepted, next question please".
  // (Hooks must run on every render, so this sits above the early returns.)
  useAttemptUpdates(attemptId, token, reload, attempt?.current_step === "evaluating");

  // Only show "Loading" the FIRST time. When we reload after each answer,
  // keep showing the page, so the camera doesn't flicker off and on.
  if (loading && !attempt) return <p className="muted">Loading interview...</p>;
  if (error) return <p className="error">{error.message}</p>;
  if (!attempt) return null;

  if (attempt.current_step === "finished") {
    return (
      <div className="card">
        <h1>Interview complete</h1>
        <p>All five answers are saved.</p>
        <Link className="button" to={`/attempts/${attempt.attempt_id}/review`}>
          See your results
        </Link>
      </div>
    );
  }

  const question = attempt.questions.find((q) => q.order === attempt.current_question);
  if (!question) return <p className="error">Couldn't find the current question.</p>;

  async function submitAnswer(video: Blob, contentType: string) {
    if (!attempt || !question) return;
    setSubmitError(null);
    setUploadPercent(0);
    const base = `/attempts/${attempt.attempt_id}/questions/${question.order}`;

    try {
      if (video.size > attempt.limits.max_upload_bytes) {
        throw new Error("This recording is too large. Please record a shorter answer.");
      }
      // Step 1: permission slip from our backend. The backend works out by
      // itself whether this is the main answer or a follow-up answer.
      const ticket = await apiPost<UploadUrlResponse>(`${base}/upload-url`, token, {
        content_type: contentType,
        size_bytes: video.size,
      });
      // Step 2: the video goes directly to S3
      await uploadToS3(ticket.upload_url, video, ticket.upload_headers, setUploadPercent);
      // Step 3: "done" - the backend checks S3, then either moves on (knowledge
      // questions) or starts the STAR check (situational questions)
      const result = await apiPost<CompleteRecordingResponse>(
        `${base}/recordings/${ticket.recording_id}/complete`,
        token,
      );

      if (result.status === "completed") {
        navigate(`/attempts/${attempt.attempt_id}/review`);
      } else {
        reload(); // fetch the attempt again to find out what comes next
      }
    } catch (err) {
      // The recording stays in the recorder, so the user can just press
      // Submit again - the backend safely replaces the unfinished upload.
      setSubmitError((err as Error).message);
    } finally {
      setUploadPercent(null);
    }
  }

  const answeredCount = attempt.questions.filter((q) => q.answered).length;
  const followUp = attempt.current_step === "record_follow_up" ? attempt.pending_follow_up : null;

  return (
    <>
      <p className="muted">
        {attempt.interview_title} &middot; Question {question.order} of {attempt.questions.length}
      </p>
      <progress className="progress" value={answeredCount} max={attempt.questions.length} />

      {followUp ? (
        <>
          {/* Keep the original question visible, but smaller. */}
          <p className="muted">
            <span className={`badge ${question.type}`}>{question.type}</span>
            {question.text}
          </p>
          <h1>
            <span className="badge follow-up">
              follow-up {followUp.number} of up to {attempt.limits.max_follow_ups}
            </span>
            {followUp.question}
          </h1>
          <p className="muted">A short answer that fills in this part of your story is perfect.</p>
        </>
      ) : (
        <>
          <h1>
            <span className={`badge ${question.type}`}>{question.type}</span>
            {question.text}
          </h1>
          {question.type === "situational" && (
            <p className="muted">
              Tip: structure your answer with STAR - the Situation, your Task, the Action you took, and the Result.
              If anything's missing, you'll get a follow-up question.
            </p>
          )}
        </>
      )}

      {attempt.current_step === "evaluating" ? (
        <div className="card waiting">
          <span className="spinner" aria-hidden="true" />
          {WAITING_LABELS[question.processing_status ?? "queued"] ?? "Reviewing your answer..."}
          <p className="muted">This usually takes under a minute. You can stay on this page.</p>
        </div>
      ) : (
        // A new `key` gives each recording a brand-new recorder, so nothing
        // from the previous answer (or follow-up) carries over.
        <VideoRecorder
          key={`${question.order}-${followUp?.number ?? 0}`}
          maxSeconds={attempt.limits.max_recording_seconds}
          allowedContentTypes={attempt.limits.allowed_content_types}
          busy={uploadPercent !== null}
          onSubmit={submitAnswer}
        />
      )}

      {uploadPercent !== null && (
        <p className="muted">
          Uploading... {uploadPercent}%
          <progress className="progress" value={uploadPercent} max={100} />
        </p>
      )}
      {submitError && <p className="error">{submitError} You can press Submit again to retry.</p>}
    </>
  );
}
