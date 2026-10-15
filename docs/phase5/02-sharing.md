# 02 Sharing

Every finished answer now has a **visibility**: `"private"` (the default, only its owner can see it) or `"shared"` (it appears on the Community pages and in search). Only the owner can change it. Shared answers show the transcript and feedback, **never the video or the owner's name**.

---

## `backend/app/models.py`: the visibility type

**Where and when it's used:** FastAPI uses these models to check incoming requests and filter outgoing responses for the sharing endpoints and the review page.

```python
Visibility = Literal["private", "shared"]
```

- A **type alias**: a name for "a string that must be exactly `private` or `shared`". Anything else, like `"public"`, is rejected with a 422 error before our code runs. There's a test proving this (chapter 08).

### On each question in an attempt

```python
    visibility: Visibility = "private"
```

- Added to `AttemptQuestion`, the shape of each question on the review page. It tells the page whether to show the share checkbox as ticked. It defaults to `"private"`, which also covers answers created before Phase 5, which have no `visibility` field stored.

### The request and response for changing it

```python
class VisibilityRequest(BaseModel):
    visibility: Visibility
```

- What the browser sends: `{"visibility": "shared"}` or `{"visibility": "private"}`.

```python
class VisibilityResponse(BaseModel):
    visibility: Visibility
    changed: int  # how many answers were updated
```

- What the backend replies: the new visibility, and how many answers actually changed. `changed` is `0` if it already had that visibility.

---

## `backend/app/routers/attempts.py`

**Where and when it's used:** the review page calls these endpoints when the owner ticks a share box, or clicks "Share all answers" or "Make all private".

### Including visibility in the attempt details

```python
            "visibility": answer.get("visibility", "private"),
```

- One line added inside `results_for`, in `build_attempt_detail`. When the review page loads an attempt (`GET /attempts/{id}`), each answered question now includes its visibility.
- `answer.get("visibility", "private")` reads the stored value, or uses `"private"` if the field doesn't exist, for older answers.

### Sharing one answer

```python
@router.put("/{attempt_id}/questions/{order}/visibility", response_model=VisibilityResponse)
```

- Registers the function below for `PUT /attempts/{attempt_id}/questions/{order}/visibility`. **PUT** is the HTTP method for "set this to exactly this value", which fits: the request sets the visibility, and sending it twice gives the same result.
- `response_model=VisibilityResponse` makes FastAPI check and filter the reply against that model.

```python
async def set_answer_visibility(
    attempt_id: str,
    order: int,
    body: VisibilityRequest,
    db: AsyncDatabase = Depends(get_db),
    user: dict = Depends(get_current_user),
):
```

- `attempt_id` and `order` come from the address. `body` is the JSON the browser sends, checked against `VisibilityRequest`.
- `db` and `user` are provided by FastAPI's dependency injection: the database, and the logged-in user (a request without a valid token gets 401 before this function runs).

```python
    attempt = await load_own_attempt(db, attempt_id, user)  # <- only the owner gets past this
```

- The ownership check from Phase 2: it finds the attempt **only if it belongs to this user**, and otherwise raises 404. So nobody can share, or un-share, someone else's answer.

```python
    result = await db.answers.update_one(
        {"attempt_id": attempt["_id"], "question_order": order, "status": "answered"},
        {"$set": {"visibility": body.visibility}},
    )
```

- Updates the one answer for this attempt and question number, but only if its `status` is `"answered"`. A half-recorded answer, or one still waiting for a STAR check, can't be shared, since it would be confusing for others to see.
- `{"$set": {...}}` changes just the `visibility` field and leaves the rest of the document alone.
- `result` reports what happened: `matched_count` (how many documents fitted the filter) and `modified_count` (how many actually changed).

```python
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="No finished answer to share for this question")
```

- If no finished answer exists for that question, say so with a 404.

```python
    return {"visibility": body.visibility, "changed": result.modified_count}
```

- Reply with the new visibility and whether anything changed.

### Sharing a whole interview

```python
@router.put("/{attempt_id}/visibility", response_model=VisibilityResponse)
async def set_attempt_visibility(
    attempt_id: str,
    body: VisibilityRequest,
    db: AsyncDatabase = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    attempt = await load_own_attempt(db, attempt_id, user)
```

- Same idea for `PUT /attempts/{attempt_id}/visibility`, with the same ownership check, but no question number.

```python
    result = await db.answers.update_many(
        {"attempt_id": attempt["_id"], "status": "answered"},
        {"$set": {"visibility": body.visibility}},
    )
    return {"visibility": body.visibility, "changed": result.modified_count}
```

- `update_many` changes **every** finished answer in this attempt at once. This endpoint never returns 404 for "nothing to share": if there are no finished answers, `changed` is simply `0`.

---

## `frontend/src/api.ts`: a PUT helper

**Where and when it's used:** by `ShareToggle.tsx` and `AttemptReviewPage.tsx` to call the endpoints above.

```typescript
  method: "GET" | "POST" | "PUT",
```

- In `apiRequest`, the list of allowed methods gained `"PUT"`. TypeScript now refuses a typo like `"PTU"`.

```typescript
export const apiPut = <T>(path: string, accessToken?: string, body?: unknown) =>
  apiRequest<T>("PUT", path, accessToken, body);
```

- A shortcut, like the existing `apiGet` and `apiPost`: `apiPut(path, token, body)` sends a PUT request with the login token and a JSON body.
- `<T>` lets the caller say what shape of reply to expect, for example `apiPut<VisibilityResponse>(...)`.

---

## `frontend/src/types.ts`

```typescript
export type Visibility = "private" | "shared";
```

- The TypeScript version of the backend's `Visibility`.

```typescript
  visibility: Visibility;
```

- Added to `AttemptQuestion`, matching the backend model.

```typescript
export interface VisibilityResponse {
  visibility: Visibility;
  changed: number;
}
```

- Matches the backend's `VisibilityResponse`.

---

## `frontend/src/components/ShareToggle.tsx`

**Where and when it's used:** the review page shows one of these under every finished answer.

```typescript
import { useState } from "react";
import { apiPut } from "../api";
import type { Visibility, VisibilityResponse } from "../types";
```

- `useState` stores values that change over time; `apiPut` sends the change; the types describe the data.

```typescript
interface Props {
  attemptId: string;
  order: number;
  visibility: Visibility;
  token?: string;
  onChanged: () => void; // tells the page to reload, so everything stays in sync
}
```

- What the parent page must pass in: which answer this is (`attemptId` and `order`), its current visibility, the login token (`?` means it might be missing), and a function to call after a change.
- `() => void` means "a function that takes nothing and returns nothing".

```typescript
export default function ShareToggle({ attemptId, order, visibility, token, onChanged }: Props) {
```

- The component. The `{ ... }: Props` part unpacks the props into separate variables.

```typescript
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
```

- `saving` is `true` while the request is in progress, which disables the checkbox so it can't be double-clicked.
- `error` holds an error message to show, or `null` when there isn't one.

```typescript
  async function toggle(shared: boolean) {
    setSaving(true);
    setError(null);
```

- Runs when the checkbox changes. `shared` is `true` if it was just ticked. It marks the start of saving and clears any old error.

```typescript
    try {
      await apiPut<VisibilityResponse>(`/attempts/${attemptId}/questions/${order}/visibility`, token, {
        visibility: shared ? "shared" : "private",
      });
      onChanged();
```

- Sends the PUT request to the one-answer endpoint. `shared ? "shared" : "private"` turns the true/false into the word the backend expects.
- After it succeeds, `onChanged()` tells the page to reload the attempt. The checkbox doesn't change its own state: it shows whatever the **backend** now says, so the screen can never show "shared" for an answer that isn't.

```typescript
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSaving(false);
    }
  }
```

- If the request fails, show the backend's message. `finally` runs either way, so the checkbox is re-enabled whether it worked or not.

```tsx
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
```

- A checkbox inside a `<label>`, so clicking the words also toggles it.
- `checked={visibility === "shared"}` ticks it when the answer is shared.
- `disabled={saving}` greys it out while saving.
- `onChange` runs when it's clicked, passing the new ticked state (`event.target.checked`) to `toggle`.

```tsx
      <p className="muted small">
        Others see your transcript and feedback - never your video or your name. You can stop sharing at any time.
      </p>
      {error && <p className="error">{error}</p>}
    </div>
  );
}
```

- Tells the user exactly what sharing means, before they decide. Being clear about what's shared is part of getting consent properly.
- `{error && ...}` shows the error paragraph only when there is an error.

---

## `frontend/src/pages/AttemptReviewPage.tsx`: the sharing controls

**Where and when it's used:** the page where an owner watches their answers back.

### Imports

```typescript
import { useState } from "react";
import { apiPut, useApi } from "../api";
import ShareToggle from "../components/ShareToggle";
```

- `useState` for the "Share all" buttons, `apiPut` to send the change, and the new component.

### Share or un-share everything

```typescript
  const [sharingAll, setSharingAll] = useState(false);
```

- `true` while a "Share all" or "Make all private" request is running, to disable the buttons.
- It sits **above** the page's early `return`s (like "Loading..."). React requires hooks like `useState` to run in the same order on every render, so they can't come after a `return` that only sometimes happens.

```typescript
  async function setAllVisibility(visibility: "shared" | "private") {
    setSharingAll(true);
    try {
      await apiPut(`/attempts/${attemptId}/visibility`, token, { visibility });
      reload();
    } finally {
      setSharingAll(false);
    }
  }
```

- Calls the whole-interview endpoint, then reloads the attempt so every checkbox updates.
- `{ visibility }` is shorthand for `{ visibility: visibility }`.

### The buttons

```tsx
      {attempt.questions.some((q) => q.answered) && (
        <div className="share-all">
          <span className="muted">Help others practise:</span>
          <button className="button secondary" disabled={sharingAll} onClick={() => setAllVisibility("shared")}>
            Share all answers
          </button>
          <button className="button secondary" disabled={sharingAll} onClick={() => setAllVisibility("private")}>
            Make all private
          </button>
        </div>
      )}
```

- Only shown if at least one answer is finished (`.some(...)` is true if any item matches), since there's nothing to share otherwise.
- `onClick={() => setAllVisibility("shared")}` wraps the call in a small function, so it runs on click rather than immediately when the page draws.

### One toggle per answer

```tsx
              {question.answered && (
                <ShareToggle
                  attemptId={attempt.attempt_id}
                  order={question.order}
                  visibility={question.visibility}
                  token={token}
                  onChanged={reload}
                />
              )}
```

- Under each answer's results, but only for finished answers.
- `onChanged={reload}` passes the page's own `reload` function, so after a change the page fetches the attempt again and shows the new visibility.
