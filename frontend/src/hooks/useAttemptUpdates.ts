// useAttemptUpdates.ts - Listen for live processing updates over a WebSocket.
//
// The server sends a short message whenever an answer moves along
// (queued -> transcribing -> scoring -> done). We don't use the message's
// details directly: we just call onUpdate(), and the page fetches fresh data
// from the API. The database stays the source of truth; this is the doorbell.

import { useEffect, useRef } from "react";
import { config } from "../config";

export function useAttemptUpdates(
  attemptId: string | undefined,
  accessToken: string | undefined,
  onUpdate: () => void,
  enabled: boolean,
) {
  // Keep the latest onUpdate in a ref, so a new function on every render
  // doesn't make us disconnect and reconnect.
  const onUpdateRef = useRef(onUpdate);
  onUpdateRef.current = onUpdate;

  useEffect(() => {
    if (!enabled || !attemptId || !accessToken) return;

    let socket: WebSocket | null = null;
    let stopped = false;
    let retryDelay = 1000;
    let retryTimer: number | undefined;

    function connect() {
      // http://localhost:8000 -> ws://localhost:8000 (and https -> wss).
      const url = `${config.apiUrl.replace(/^http/, "ws")}/ws/attempts/${attemptId}`;
      socket = new WebSocket(url);

      socket.onopen = () => {
        retryDelay = 1000;
        // Browsers can't attach an Authorization header to a WebSocket,
        // so the access token goes in the first message instead.
        socket?.send(JSON.stringify({ type: "auth", token: accessToken }));
      };

      socket.onmessage = (event) => {
        const message = JSON.parse(event.data);
        if (message.type === "processing_update") onUpdateRef.current();
      };

      socket.onclose = (event) => {
        if (stopped) return;
        // 1008 = the server refused us (not logged in, not our attempt).
        // Reconnecting wouldn't help, so stop.
        if (event.code === 1008) return;
        // Anything else (Wi-Fi blip, server restart): reconnect, waiting a
        // little longer each time, up to 30 seconds ("exponential backoff").
        // On reconnecting, the server sends the current state, so we catch up.
        retryTimer = window.setTimeout(connect, retryDelay);
        retryDelay = Math.min(retryDelay * 2, 30_000);
      };
    }

    connect();

    // Leaving the page: close the connection and cancel any planned retry.
    return () => {
      stopped = true;
      window.clearTimeout(retryTimer);
      socket?.close();
    };
  }, [attemptId, accessToken, enabled]);
}
