# Phase 2: Recording answers

This phase turns the interview page into a real interview:

- Choose an interview, agree to being recorded, and answer **one question at a time** on camera
- Watch your recording back, **re-record** if you want, then submit
- Videos upload **straight from the browser to S3** using presigned URLs, with a progress bar
- The backend **checks** each upload really arrived, then moves you to the next question
- A **My interviews** page, and a page to **watch your answers back**
- 22 new automated tests (38 in total), using a fake S3 so tests never touch your real bucket

Transcription and scoring come in Phase 3. For now, the goal is: record, store safely, play back.

Commands are for **Windows PowerShell**. Your region is **eu-north-1 (Stockholm)** throughout.

---

## How it works

```
 Browser                          Backend (FastAPI)                 S3 bucket
    |  1. "I recorded 12 MB of webm"    |                                |
    | --------------------------------> |  checks: your attempt? right   |
    |                                   |  question? allowed type/size?  |
    |  2. presigned upload URL          |                                |
    | <-------------------------------- |                                |
    |  3. PUT the video directly ------------------------------------->  |
    |  4. "upload finished"             |                                |
    | --------------------------------> |  5. HEAD: is it really there?  |
    |                                   | -----------------------------> |
    |  6. "next question: 2"            |                                |
    | <-------------------------------- |                                |
```

The video never passes through your backend, and the backend never trusts the browser's word that an upload worked: it checks S3 itself (step 5).

---

## Step 1: Get the new code onto a branch

Your `main` branch is protected now, so all new work goes through a branch and pull request:

```powershell
git checkout main
git pull
git checkout -b phase-2-recording
```

Then copy the files from this phase into your project.

**New files:**

| File | What it does |
|---|---|
| `backend/app/storage.py` | All S3 code: presigned URLs, checking uploads |
| `backend/app/routers/attempts.py` | Starting interviews, uploads, playback links |
| `backend/tests/test_attempts.py` | 22 tests for all of the above |
| `frontend/src/components/VideoRecorder.tsx` | Camera, recording, timer, preview |
| `frontend/src/pages/AttemptPage.tsx` | The interview screen, one question at a time |
| `frontend/src/pages/AttemptReviewPage.tsx` | Watch your answers back |
| `frontend/src/pages/MyInterviewsPage.tsx` | List of your attempts |

**Changed files:** `backend/app/config.py`, `db.py`, `main.py`, `models.py`, `backend/requirements.txt`, `requirements-dev.txt`, `backend/.env.example`, `backend/tests/conftest.py`, and in the frontend `src/App.tsx`, `api.ts`, `types.ts`, `index.css`, `components/Header.tsx`, `pages/InterviewPage.tsx`, and `.env.example`.

> Don't copy over your real `backend/.env` or `frontend/.env.local`. Only the `.env.example` templates changed, and you'll add the new settings to your real files by hand in Step 5.

Suggested reading order: `storage.py` → `routers/attempts.py` (start at `create_upload_url`) → `VideoRecorder.tsx` → `AttemptPage.tsx` → `api.ts` (`uploadToS3`).

---

## Step 2: Create the S3 bucket

1. In the AWS console, search for **S3** and open it. Check the region shown is **Stockholm (eu-north-1)**.
2. Click **Create bucket**.
3. **Bucket type:** General purpose (if asked).
4. **Bucket name:** must be unique across *all* of AWS worldwide, lowercase, no spaces. For example: `mock-interview-dev-videos-bilal`. Write it down.
5. **AWS Region:** Europe (Stockholm) eu-north-1, if this option appears.
6. **Object Ownership:** leave as **ACLs disabled**.
7. **Block Public Access:** leave **Block all public access** ticked. This is important: the videos must never be public. Your app only ever shares them through temporary presigned links.
8. Leave everything else as default (encryption is on automatically), and click **Create bucket**.

---

## Step 3: Allow the browser to upload (CORS)

Remember CORS from Phase 1: browsers block a website from talking to a different address unless that address allows it. Your app at `localhost:5173` is about to send videos to `your-bucket.s3.eu-north-1.amazonaws.com`, so the **bucket** has to allow it.

1. Open your bucket → **Permissions** tab → scroll to **Cross-origin resource sharing (CORS)** → **Edit**.
2. Paste this, then **Save changes**:

```json
[
  {
    "AllowedOrigins": ["http://localhost:5173"],
    "AllowedMethods": ["PUT", "GET"],
    "AllowedHeaders": ["Content-Type"],
    "ExposeHeaders": ["ETag"],
    "MaxAgeSeconds": 3000
  }
]
```

This says: "code running on `http://localhost:5173` may upload (PUT) and fetch (GET) files here, sending a `Content-Type` header." Any other website is still blocked. In Phase 6, the staging and prod buckets get their own CORS rules with their real addresses.

### Optional but recommended: auto-delete old dev videos

Test recordings pile up. A **lifecycle rule** tells S3 to delete them automatically, which saves money and is good privacy practice:

1. Bucket → **Management** tab → **Create lifecycle rule**.
2. Name: `delete-old-dev-videos`. Scope: **Limit the scope using filters**, prefix `videos/`.
3. Tick **Expire current versions of objects**, and enter **30** days.
4. Acknowledge and **Create rule**.

---

## Step 4: Give your laptop permission to use the bucket

Your backend needs AWS credentials to create presigned URLs. On AWS itself (Phase 6), it'll get permissions from an **IAM role**, with no keys at all. On your laptop, the usual approach is an **IAM user** with **access keys**, given the *least* permission possible: only these few actions, on only this one bucket.

> IAM (Identity and Access Management) is AWS's permissions system. A **policy** is a list of what's allowed; a **user** is an identity the policy is attached to.

### 4a. Create the policy

1. Search for **IAM** and open it → **Policies** → **Create policy**.
2. Switch the editor to **JSON** and paste this, replacing `YOUR-BUCKET-NAME` with your bucket's name:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "DevVideoBucketObjects",
      "Effect": "Allow",
      "Action": ["s3:PutObject", "s3:GetObject", "s3:DeleteObject"],
      "Resource": "arn:aws:s3:::YOUR-BUCKET-NAME/*"
    }
  ]
}
```

3. **Next**, name it `mock-interview-dev-videos-access`, and **Create policy**.

What this allows: uploading (`PutObject`), reading and checking files (`GetObject`, which also covers the "is it really there?" check), and deleting them (`DeleteObject`), only inside your one bucket. It can't touch any other bucket, list your files, or use any other AWS service, so even if these keys ever leaked, the damage would be limited to this bucket.

### 4b. Create the user and attach the policy

1. IAM → **Users** → **Create user**.
2. Name: `mock-interview-dev-local`. Do **not** give it console access; it's only for code.
3. **Permissions:** **Attach policies directly** → search for `mock-interview-dev-videos-access` → tick it → **Next** → **Create user**.

### 4c. Create access keys

1. Open the new user → **Security credentials** tab → **Create access key**.
2. Use case: **Local code** (or "Application running outside AWS"). AWS will suggest alternatives; acknowledge and continue.
3. You'll see an **Access key ID** and a **Secret access key**. The secret is shown **only once**, so copy both now.

> Treat these exactly like a password. Never put them in code, screenshots, chat messages, or GitHub. If they ever leak, open this user → **Security credentials** and **deactivate** the key, then create a new one.

> If IAM won't let you create users or keys on your account's free plan, send me a screenshot of what you see and we'll find another way.

---

## Step 5: Update your settings

Add these to the end of your real **`backend/.env`**:

```
AWS_REGION=eu-north-1
S3_VIDEOS_BUCKET=your-bucket-name
AWS_ACCESS_KEY_ID=paste-the-access-key-id
AWS_SECRET_ACCESS_KEY=paste-the-secret-access-key
```

`.env` is already ignored by Git, so the keys stay on your machine. Before committing later, `git status` should still never show `backend/.env`.

The frontend needs no new settings: it never talks to AWS with keys, only with the presigned URLs the backend gives it.

---

## Step 6: Install, rebuild and test

The backend has new packages (`boto3` for AWS, and `moto` for tests).

1. **Tests**, in the `backend` folder with your virtual environment active:

   ```powershell
   pip install -r requirements-dev.txt
   pytest -v
   ```

   **Check:** `38 passed`. These use the fake S3 (moto), so they pass even before your bucket exists, and your real keys are never used.

2. **Rebuild the backend container.** The `--build` part matters: the Docker image has to be rebuilt to include `boto3`.

   ```powershell
   docker compose down
   docker compose up --build
   ```

   If `S3_VIDEOS_BUCKET` is missing, the logs show a warning: `S3_VIDEOS_BUCKET is not set`.

3. **Frontend:** `npm run dev` as usual. No new packages.

---

## Step 7: Try it out

1. Open http://localhost:5173 and log in.
2. Pick an interview → **Start**. Read the intro, tick the consent box, and **Start interview**.
3. Your browser asks for **camera and microphone** permission. Allow it.
4. **Start recording**, say a few words, **Stop**. Watch it back, try **Re-record** once, then **Submit answer**. You'll see the upload percentage, then question 2 appears.
5. Answer all five (short answers are fine for testing). You land on the review page, where every answer plays back.
6. Click **My interviews** in the header to see the attempt listed.

**Check it on AWS:** open your bucket → **Objects**. You'll find `videos/` → a folder named after your user ID → a folder for the attempt → files like `q1-....webm`. Try clicking one and opening its **Object URL**: you'll get **Access Denied**. That's the bucket correctly staying private. Only presigned links work.

**Check it in MongoDB:**

```powershell
docker compose exec mongo mongosh
```

```javascript
use mock_interview_dev
db.attempts.find()
db.answers.find({}, { question_order: 1, status: 1, "recordings.video_key": 1 })
```

Notice `consented_to_recording_at` on the attempt, and that each answer stores the video's **location** in S3, not the video itself.

**Try the privacy rule:** once you've completed an attempt, log out and register a second account. Visit `http://localhost:5173/attempts/<the first account's attempt ID>/review`. You'll get "Interview attempt not found": the backend refuses to show another user's interview, and doesn't even confirm it exists.

---

## Step 8: Commit through a pull request

```powershell
git status          # backend/.env must NOT appear
git add .
git commit -m "Phase 2: record answers and upload to S3"
git push -u origin phase-2-recording
```

On GitHub, open a pull request, wait for the three green checks, and merge. Then:

```powershell
git checkout main
git pull
```

CI needs no changes and no AWS keys, because the tests use the fake S3.

---

## Troubleshooting

| Problem | Likely cause and fix |
|---|---|
| "Video storage isn't configured" | `S3_VIDEOS_BUCKET` is missing from `backend/.env`, or you didn't restart with `docker compose up --build`. |
| "Upload failed - check your connection and the bucket's CORS settings" | The CORS rule is missing or wrong (Step 3). The origin must be exactly `http://localhost:5173`, with no trailing slash. |
| "Upload failed (S3 responded 403)" | Usually wrong keys, a policy with the wrong bucket name, or a bucket in a different region from `AWS_REGION`. Also check your computer's clock is correct: signatures include the time. |
| "The video hasn't finished uploading yet" right after a successful upload | The policy is missing `s3:GetObject`, which the backend needs to check the file. |
| Camera permission was blocked | Click the camera icon in the browser's address bar, allow access, and reload. |
| Camera stays black, or "being used by another app" | Close Zoom, Teams, or the Windows Camera app, then reload. |
| `InvalidAccessKeyId` or `SignatureDoesNotMatch` in the backend logs | The access key or secret in `.env` has a typo or extra space. Copy them again. |
| Tests fail with `ModuleNotFoundError: moto` or `boto3` | Run `pip install -r requirements-dev.txt` in the virtual environment. |

---

## What's next

**Phase 3:** when an answer is submitted, a job goes onto an **SQS** queue, a **worker** transcribes the video and scores knowledge answers, and a **WebSocket** pushes the result to the browser as soon as it's ready.
