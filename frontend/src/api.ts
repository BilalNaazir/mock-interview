// api.ts - Everything related to talking to our FastAPI backend.

import { useEffect, useState } from "react";
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

// Make a GET request to the API. If we have an access token (the user is
// logged in), attach it as "Authorization: Bearer <token>" - this is what
// the backend's get_current_user checks.
export async function apiGet<T>(path: string, accessToken?: string): Promise<T> {
  const headers: Record<string, string> = {};
  if (accessToken) {
    headers.Authorization = `Bearer ${accessToken}`;
  }

  const response = await fetch(`${config.apiUrl}${path}`, { headers });

  if (!response.ok) {
    // FastAPI puts error messages in a "detail" field.
    const body = await response.json().catch(() => ({}));
    throw new ApiError(response.status, body.detail ?? `Request failed (${response.status})`);
  }
  return response.json() as Promise<T>;
}

// A reusable React "hook" that loads data and tracks the three states every
// data-loading screen needs: loading, error, and success.
export function useApi<T>(path: string | null, accessToken?: string) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<ApiError | Error | null>(null);
  const [loading, setLoading] = useState(path !== null);

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
  }, [path, accessToken]);

  return { data, error, loading };
}
