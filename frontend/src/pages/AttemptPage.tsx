// AttemptPage.tsx - The interview itself: one question at a time.
//
// For each answer, submitting runs three steps:
//   1. Ask OUR backend for a presigned upload URL
//   2. Upload the video STRAIGHT TO S3 with that URL (with a progress bar)
//   3. Tell our backend the upload finished, so it can check and move on
import { useState } from "react";
import { useAuth } from "react-oidc-context";
import { Link, useNavigate, useParams } from "react-router";
import { apiPost, uploadToS3, useApi } from "../api";
import VideoRecorder from "../components/VideoRecorder";
import type { AttemptDetail, CompleteRecordingResponse, UploadUrlResponse } from "../types";

export default function AttemptPage() {
  const { attemptId } = useParams();
  const auth = useAuth();
  const token = auth.user?.access_token;
  const navigate = useNavigate();
  const { data: attempt, error, loading, reload } = useApi<AttemptDetail>(`/attempts/${attemptId}`, token);

  const [uploadPercent, setUploadPercent] = useState<number | null>(null);
  const [submitError, setSubmitError] = useState<string | null>(null);

  // Only show "Loading" the FIRST time. When we reload after each answer,
  // keep showing the page, so the camera doesn't flicker off and on.
  if (loading && !attempt) return <p className="muted">Loading interview...</p>;
  if (error) return <p className="error">{error.message}</p>;
  if (!attempt) return null;

  if (attempt.status === "completed") {
    return (
      <div className="card">
        <h1>Interview complete</h1>
        <p>All five answers are saved.</p>
        <Link className="button" to={`/attempts/${attempt.attempt_id}/review`}>
          Watch your answers
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
      // Step 1: permission slip from our backend
      const ticket = await apiPost<UploadUrlResponse>(`${base}/upload-url`, token, {
        content_type: contentType,
        size_bytes: video.size,
      });
      // Step 2: the video goes directly to S3
      await uploadToS3(ticket.upload_url, video, ticket.upload_headers, setUploadPercent);
      // Step 3: "done" - the backend checks S3 and moves to the next question
      const result = await apiPost<CompleteRecordingResponse>(
        `${base}/recordings/${ticket.recording_id}/complete`,
        token,
      );

      if (result.status === "completed") {
        navigate(`/attempts/${attempt.attempt_id}/review`);
      } else {
        reload(); // fetch the attempt again, which now points at the next question
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

  return (
    <>
      <p className="muted">
        {attempt.interview_title} &middot; Question {question.order} of {attempt.questions.length}
      </p>
      <progress className="progress" value={answeredCount} max={attempt.questions.length} />

      <h1>
        <span className={`badge ${question.type}`}>{question.type}</span>
        {question.text}
      </h1>
      {question.type === "situational" && (
        <p className="muted">
          Tip: structure your answer with STAR - the Situation, your Task, the Action you took, and the Result.
        </p>
      )}

      {/* key={question.order} gives each question a brand-new recorder, so
          nothing from the previous answer carries over. */}
      <VideoRecorder
        key={question.order}
        maxSeconds={attempt.limits.max_recording_seconds}
        allowedContentTypes={attempt.limits.allowed_content_types}
        busy={uploadPercent !== null}
        onSubmit={submitAnswer}
      />

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
