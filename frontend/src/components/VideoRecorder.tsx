// VideoRecorder.tsx - Records one answer with the webcam and microphone.
//
// It moves through these stages (a "state machine"):
//
//   starting  -> asking the browser for camera + microphone access
//   ready     -> live camera preview, waiting for "Start recording"
//   recording -> recording, with a timer that stops automatically at the limit
//   recorded  -> playback of what was just recorded: re-record or submit
//   error     -> something went wrong (e.g. permission denied)
//
// Two browser features do the work:
//   - getUserMedia() turns on the camera and microphone and gives us a "stream"
//   - MediaRecorder records that stream into a video file (a Blob)
//
// Note: browsers only allow camera access on secure pages (https://), with
// one exception for development: http://localhost.

import { useEffect, useRef, useState } from "react";

type Stage = "starting" | "ready" | "recording" | "recorded" | "error";

interface Recording {
  blob: Blob;         // the video file, held in the browser's memory
  url: string;        // a temporary local address so a <video> can play it
  contentType: string;
}

interface Props {
  maxSeconds: number;
  allowedContentTypes: string[];
  busy: boolean; // true while the parent is uploading
  onSubmit: (video: Blob, contentType: string) => Promise<void>;
}

// Different browsers can record different formats. We try the best ones
// first and use the first one this browser supports AND the backend accepts.
const PREFERRED_FORMATS = [
  "video/webm;codecs=vp9,opus", // Chrome, Edge
  "video/webm;codecs=vp8,opus", // Firefox, older Chrome
  "video/webm",
  "video/mp4;codecs=avc1,mp4a", // Safari
  "video/mp4",
];

function pickFormat(allowed: string[]): string | null {
  return (
    PREFERRED_FORMATS.find(
      (format) => allowed.includes(format.split(";")[0]) && MediaRecorder.isTypeSupported(format),
    ) ?? null
  );
}

function describeCameraError(error: unknown): string {
  const name = error instanceof DOMException ? error.name : "";
  if (name === "NotAllowedError") {
    return "Camera or microphone access was blocked. Allow access using the icon in the address bar, then reload the page.";
  }
  if (name === "NotFoundError") return "No camera or microphone was found on this device.";
  if (name === "NotReadableError") return "Your camera is being used by another app. Close it and reload the page.";
  return "Couldn't start the camera. Try reloading the page.";
}

function formatTime(totalSeconds: number): string {
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = String(totalSeconds % 60).padStart(2, "0");
  return `${minutes}:${seconds}`;
}

export default function VideoRecorder({ maxSeconds, allowedContentTypes, busy, onSubmit }: Props) {
  // useRef holds values that must survive re-renders but shouldn't cause
  // one when they change - like the camera stream and the recorder itself.
  const liveVideoRef = useRef<HTMLVideoElement>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);

  const [stage, setStage] = useState<Stage>("starting");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [elapsed, setElapsed] = useState(0);
  const [recording, setRecording] = useState<Recording | null>(null);

  // 1. Turn the camera on when this component appears, and OFF when it goes.
  //    Forgetting the "off" part is a classic bug: the camera light stays on
  //    after the user leaves the page.
  useEffect(() => {
    let cancelled = false;

    if (typeof MediaRecorder === "undefined" || !navigator.mediaDevices) {
      setErrorMessage("This browser can't record video. Please use a recent Chrome, Edge, Firefox or Safari.");
      setStage("error");
      return;
    }

    navigator.mediaDevices
      // Modest quality keeps files small: about 7-8 MB per minute.
      .getUserMedia({ video: { width: { ideal: 640 }, height: { ideal: 480 } }, audio: true })
      .then((stream) => {
        if (cancelled) {
          // The user left before the camera started - switch it straight off.
          stream.getTracks().forEach((track) => track.stop());
          return;
        }
        streamRef.current = stream;
        if (liveVideoRef.current) liveVideoRef.current.srcObject = stream;
        setStage("ready");
      })
      .catch((error) => {
        if (!cancelled) {
          setErrorMessage(describeCameraError(error));
          setStage("error");
        }
      });

    return () => {
      cancelled = true;
      if (recorderRef.current?.state === "recording") recorderRef.current.stop();
      streamRef.current?.getTracks().forEach((track) => track.stop());
      streamRef.current = null;
    };
  }, []);

  // 2. While recording, count the seconds.
  useEffect(() => {
    if (stage !== "recording") return;
    const timer = window.setInterval(() => setElapsed((s) => s + 1), 1000);
    return () => window.clearInterval(timer);
  }, [stage]);

  // 3. Stop automatically at the time limit.
  useEffect(() => {
    if (stage === "recording" && elapsed >= maxSeconds) {
      recorderRef.current?.stop();
    }
  }, [stage, elapsed, maxSeconds]);

  // 4. Free the memory used by a recording when it's replaced or we leave.
  useEffect(() => {
    return () => {
      if (recording) URL.revokeObjectURL(recording.url);
    };
  }, [recording]);

  function startRecording() {
    const format = pickFormat(allowedContentTypes);
    if (!format || !streamRef.current) {
      setErrorMessage("This browser can't record in a supported video format.");
      setStage("error");
      return;
    }

    chunksRef.current = [];
    const recorder = new MediaRecorder(streamRef.current, {
      mimeType: format,
      videoBitsPerSecond: 1_000_000,
    });
    // The recorder hands us the video in pieces ("chunks") as it goes...
    recorder.ondataavailable = (event) => {
      if (event.data.size > 0) chunksRef.current.push(event.data);
    };
    // ...and when it stops, we glue the pieces into one file.
    recorder.onstop = () => {
      const contentType = format.split(";")[0];
      const blob = new Blob(chunksRef.current, { type: contentType });
      setRecording({ blob, url: URL.createObjectURL(blob), contentType });
      setStage("recorded");
    };

    recorder.start(1000); // hand over a chunk every second
    recorderRef.current = recorder;
    setElapsed(0);
    setStage("recording");
  }

  function reRecord() {
    setRecording(null);
    setStage("ready");
  }

  if (stage === "error") {
    return <p className="error">{errorMessage}</p>;
  }

  const secondsLeft = Math.max(0, maxSeconds - elapsed);

  return (
    <div className="recorder">
      {/* The live camera view stays in the page the whole time (just hidden
          during playback), so the stream doesn't need restarting.
          It's muted, otherwise you'd hear yourself echoing. */}
      <video
        ref={liveVideoRef}
        className="recorder-video"
        autoPlay
        muted
        playsInline
        hidden={stage === "recorded"}
      />

      {stage === "recorded" && recording && (
        <video className="recorder-video" src={recording.url} controls playsInline />
      )}

      <div className="recorder-controls">
        {stage === "starting" && <span className="muted">Starting your camera...</span>}

        {stage === "ready" && (
          <button className="button" onClick={startRecording}>
            Start recording
          </button>
        )}

        {stage === "recording" && (
          <>
            <span className="recording-dot" aria-hidden="true" />
            <span>
              Recording {formatTime(elapsed)} &middot; {formatTime(secondsLeft)} left
            </span>
            <button className="button" onClick={() => recorderRef.current?.stop()}>
              Stop
            </button>
          </>
        )}

        {stage === "recorded" && recording && (
          <>
            <button className="button secondary" onClick={reRecord} disabled={busy}>
              Re-record
            </button>
            <button className="button" onClick={() => onSubmit(recording.blob, recording.contentType)} disabled={busy}>
              Submit answer
            </button>
          </>
        )}
      </div>
    </div>
  );
}
