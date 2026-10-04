// api.ts - Everything related to talking to our FastAPI backend (and S3).

import { useCallback, useEffect, useState } from "react";
import { config } from "./config";

// An error that remembers the HTTP status code (401, 404, ...), so the UI
// can react differently to "not logged in" versus "not found".
export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

// Send any request to our API. If we have an access token (the user is
// logged in), attach it as "Authorization: Bearer <token>" - this is what
// the backend's get_current_user checks.
export async function apiRequest<T>(
  method: "GET" | "POST",
  path: string,
  accessToken?: string,
  body?: unknown,
): Promise<T> {
  const headers: Record<string, string> = {};
  if (accessToken) {
    headers.Authorization = `Bearer ${accessToken}`;
  }
  if (body !== undefined) {
    headers["Content-Type"] = "application/json";
  }

  const response = await fetch(`${config.apiUrl}${path}`, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  });

  if (!response.ok) {
    // FastAPI puts error messages in a "detail" field. For validation errors
    // (422) it's a list, so we fall back to a general message.
    const data = await response.json().catch(() => ({}));
    const message = typeof data.detail === "string" ? data.detail : `Request failed (${response.status})`;
    throw new ApiError(response.status, message);
  }
  return response.json() as Promise<T>;
}

export const apiGet = <T>(path: string, accessToken?: string) => apiRequest<T>("GET", path, accessToken);
export const apiPost = <T>(path: string, accessToken?: string, body?: unknown) =>
  apiRequest<T>("POST", path, accessToken, body);

// A reusable React "hook" that loads data and tracks the three states every
// data-loading screen needs: loading, error, and success. It also returns
// reload(), for fetching fresh data after something changes.
export function useApi<T>(path: string | null, accessToken?: string) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<ApiError | Error | null>(null);
  const [loading, setLoading] = useState(path !== null);
  // Changing this number makes the effect below run again.
  const [reloadCount, setReloadCount] = useState(0);

  useEffect(() => {
    if (path === null) return; // null means "don't load anything yet"

    // If the path changes quickly (or the user leaves the page) before an
    // older request finishes, `ignore` stops that stale response from
    // overwriting newer data. This avoids a classic "race condition" bug.
    let ignore = false;
    setLoading(true);
    setError(null);

    apiGet<T>(path, accessToken)
      .then((result) => {
        if (!ignore) setData(result);
      })
      .catch((err: Error) => {
        if (!ignore) setError(err);
      })
      .finally(() => {
        if (!ignore) setLoading(false);
      });

    return () => {
      ignore = true; // React runs this "cleanup" when path/token change or the page closes
    };
  }, [path, accessToken, reloadCount]);

  const reload = useCallback(() => setReloadCount((n) => n + 1), []);
  return { data, error, loading, reload };
}

// Upload a file straight to S3 with a presigned URL. Notice there's no
// Authorization header: the permission is built into the URL itself.
//
// We use the older XMLHttpRequest instead of fetch() here for one reason:
// it can report UPLOAD progress, which fetch() can't. That's what drives the
// progress bar while a video uploads.
export function uploadToS3(
  url: string,
  file: Blob,
  headers: Record<string, string>,
  onProgress: (percent: number) => void,
): Promise<void> {
  return new Promise((resolve, reject) => {
    const request = new XMLHttpRequest();
    request.open("PUT", url);
    for (const [name, value] of Object.entries(headers)) {
      request.setRequestHeader(name, value);
    }

    request.upload.onprogress = (event) => {
      if (event.lengthComputable) {
        onProgress(Math.round((event.loaded / event.total) * 100));
      }
    };
    request.onload = () => {
      // S3 answers 200 when the upload worked. Anything else (often 403)
      // usually means the signature didn't match: wrong headers, or expired.
      if (request.status >= 200 && request.status < 300) resolve();
      else reject(new Error(`Upload failed (S3 responded ${request.status})`));
    };
    // onerror fires when the request couldn't be made at all. With S3, the
    // most common cause is a missing or wrong CORS setting on the bucket.
    request.onerror = () => reject(new Error("Upload failed - check your connection and the bucket's CORS settings"));

    request.send(file);
  });
}
