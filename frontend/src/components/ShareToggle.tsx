// ShareToggle.tsx - A checkbox for sharing one answer with other candidates.
// Used on the review page (AttemptReviewPage.tsx), once per finished answer.
import { useState } from "react";
import { apiPut } from "../api";
import type { Visibility, VisibilityResponse } from "../types";

interface Props {
  attemptId: string;
  order: number;
  visibility: Visibility;
  token?: string;
  onChanged: () => void; // tells the page to reload, so everything stays in sync
}

export default function ShareToggle({ attemptId, order, visibility, token, onChanged }: Props) {
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function toggle(shared: boolean) {
    setSaving(true);
    setError(null);
    try {
      await apiPut<VisibilityResponse>(`/attempts/${attemptId}/questions/${order}/visibility`, token, {
        visibility: shared ? "shared" : "private",
      });
      onChanged();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="share-toggle">
      <label className="checkbox">
        <input
          type="checkbox"
          checked={visibility === "shared"}
          disabled={saving}
          onChange={(event) => toggle(event.target.checked)}
        />
        Share this answer with other candidates
      </label>
      <p className="muted small">
        Others see your transcript and feedback - never your video or your name. You can stop sharing at any time.
      </p>
      {error && <p className="error">{error}</p>}
    </div>
  );
}
