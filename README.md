# Mock Interview App - Phase 1: Foundations

This phase builds the skeleton everything else hangs on:

- A **FastAPI** backend connected to **MongoDB**, listing the five interviews
- **Login and registration with AWS Cognito**, including "Continue with Google"
- A **React + TypeScript** frontend with a public interview list and a login-only interview page
- **Docker Compose** to run your dev environment with one command
- **Automated tests** and a **GitHub Actions** pipeline that checks every change
- The **dev / staging / prod** structure, ready for deployment in a later phase

Work through the steps **in order**. Each one ends with a way to check it worked, so if something breaks, you know exactly which step caused it.

Commands are shown for **Windows PowerShell**, with the Mac/Linux version underneath where it differs.

---

## The project layout

```
mock-interview/
├── .github/workflows/ci.yml   Automatic checks on every change (GitHub Actions)
├── docker-compose.yml         Runs MongoDB + the backend locally
├── .gitignore                 Files Git must never upload (like .env)
├── backend/
│   ├── Dockerfile             Recipe for the backend container image
│   ├── requirements.txt       Python packages the app needs
│   ├── requirements-dev.txt   Extra packages for testing and linting
│   ├── pyproject.toml         Settings for pytest and ruff
│   ├── .env.example           Template for your settings
│   ├── app/
│   │   ├── main.py            Where the app starts
│   │   ├── config.py          All settings (this is where dev/staging/prod differ)
│   │   ├── db.py              MongoDB connection
│   │   ├── auth.py            Checking login tokens from Cognito
│   │   ├── models.py          The exact shape of API responses
│   │   ├── seed.py            The 5 interviews and their questions
│   │   └── routers/           The endpoints, grouped by topic
│   └── tests/                 Automated tests
└── frontend/
    ├── package.json           JavaScript packages and scripts
    ├── .env.example           Template for your settings
    └── src/
        ├── main.tsx           Where the frontend starts
        ├── App.tsx            Page layout and routes
        ├── auth.ts            Login settings
        ├── api.ts             Talking to the backend
        ├── config.ts          Reads the VITE_ settings
        ├── types.ts           TypeScript versions of the API's data
        ├── components/        Header, RequireAuth
        └── pages/             HomePage, InterviewPage, NotFoundPage
```

A suggested reading order, once it's running: `config.py` → `db.py` → `main.py` → `routers/interviews.py` → `auth.py`, then `main.tsx` → `App.tsx` → `api.ts` → `pages/HomePage.tsx` → `auth.ts`. Every file is commented to explain what it does and why.

---

## Step 0: Install the tools

You need these installed once:

| Tool | Why | Check it works |
|---|---|---|
| [Git](https://git-scm.com/) | Version control | `git --version` |
| [Docker Desktop](https://www.docker.com/products/docker-desktop/) | Runs MongoDB and the backend | `docker --version` |
| [Python 3.12](https://www.python.org/downloads/) | Running tests locally | `python --version` |
| [Node.js 22 or newer (LTS)](https://nodejs.org/) | The frontend | `node --version` |

You'll also need free accounts with **GitHub**, **AWS** and **Google** (for Google Cloud Console).

> On Windows, make sure Docker Desktop is **running** (whale icon in the taskbar) before using any `docker` command.

---

## Step 1: Create the repository

1. On GitHub, create a new **empty** repository called `mock-interview` (no README, no .gitignore - we have our own).
2. Clone it and copy all the project files into it:

   ```powershell
   git clone https://github.com/YOUR-USERNAME/mock-interview.git
   cd mock-interview
   # now copy every file and folder from this project into here
   ```

3. Check the hidden files came across too: `.gitignore`, `.github/`, and the two `.env.example` files. Windows Explorer hides files starting with a dot unless you turn on **View → Show → Hidden items**.

Don't commit yet. We'll do that in Step 7, after checking that `.env` files are safely ignored.

---

## Step 2: Run MongoDB and the backend

1. Create your backend settings file from the template:

   ```powershell
   Copy-Item backend\.env.example backend\.env
   ```
   Mac/Linux: `cp backend/.env.example backend/.env`

   Leave the Cognito values as placeholders for now. The backend can start without them; only logging in needs them.

2. Start everything:

   ```powershell
   docker compose up --build
   ```

   The first run downloads images and takes a few minutes. You'll see logs from both containers. Leave this terminal running.

3. **Check it worked.** In your browser, open:
   - http://localhost:8000/health → `{"status":"ok","environment":"dev"}`
   - http://localhost:8000/interviews → a list of 5 interviews
   - http://localhost:8000/docs → interactive API documentation. Try `GET /interviews/{slug}` with `backend-python`: you'll get **401**, because it requires login. That's the protection working.

4. Try the auto-reload: in `backend/app/seed.py`, change the `description` of the Backend (Python) interview and save. The logs show the server restarting, and when you refresh `/interviews` the new description appears. That also shows the seed "upserting": it updated the existing interview instead of adding a duplicate. Change it back afterwards.

To stop everything: `Ctrl+C`, then `docker compose down`. Your data survives in a Docker volume. (`docker compose down -v` deletes the data too, for a completely fresh start.)

---

## Step 3: Run the tests locally

The tests use the MongoDB from Step 2, so keep Docker Compose running. In a **second** terminal:

```powershell
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements-dev.txt
pytest -v
ruff check .
```

Mac/Linux: use `python3 -m venv .venv` and `source .venv/bin/activate`.

**Check it worked:** `16 passed`, and ruff says `All checks passed!`

The tests use a separate `mock_interview_test` database and wipe it afterwards, so your dev data is never touched. These are exactly the checks GitHub Actions will run on every push. Running them locally first saves you from waiting for a red cross on GitHub.

> If PowerShell refuses to run `activate`, run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once, answer `Y`, then try again.

---

## Step 4: Set up login with AWS Cognito (dev)

Cognito will handle registration, passwords, email verification and Google sign-in, so our code never touches a password.

### 4a. Secure your AWS account first

If this is a new AWS account:

1. Turn on **MFA** for the root user (account menu → **Security credentials**).
2. Set a **budget alert**: search for **Budgets** in the console → **Create budget** → use the **zero spend** or monthly cost template with your email. AWS then warns you before any surprise bill.
3. Set the region selector (top right) to **Europe (London) eu-west-2**. Everything in this project uses that region.

### 4b. Create the user pool

1. In the AWS console, search for **Cognito** → **Create user pool**.
2. Choose **Single-page application (SPA)** as the application type, and name the app `mock-interview-dev`.
3. Under sign-in identifiers, choose **Email**. Keep **self-registration** enabled (so users can sign up), and add **name** as a required sign-up attribute if offered.
4. For the return URL, enter `http://localhost:5173/` (including the final `/`).
5. Create it.

> AWS updates this console fairly often, so labels may differ slightly. The important choices are: an SPA app client (no client secret), email sign-in, and self-registration on.

### 4c. Collect four values

| Value | Where to find it | Looks like |
|---|---|---|
| User pool ID | User pool **Overview** | `eu-west-2_AbC123xyz` |
| App client ID | **App clients** → your client | `4f1a2b3c...` |
| Cognito domain | **Branding → Domain** | `https://something.auth.eu-west-2.amazoncognito.com` |
| Region | | `eu-west-2` |

Put them in `backend/.env`:

```
COGNITO_USER_POOL_ID=eu-west-2_AbC123xyz
COGNITO_CLIENT_ID=4f1a2b3c...
COGNITO_DOMAIN=https://something.auth.eu-west-2.amazoncognito.com
```

Then restart the backend (`Ctrl+C` and `docker compose up` again) so it reads the new values.

### 4d. Check the app client's login settings

Open **App clients** → your client → **Login pages** → **Edit**, and make sure:

- **Allowed callback URLs:** `http://localhost:5173/`
- **Allowed sign-out URLs:** `http://localhost:5173/`
- **OAuth grant type:** Authorization code grant
- **OpenID Connect scopes:** `openid`, `email`, `profile`

These must match the frontend exactly, including the trailing slash. A mismatch here causes the most common login error, `redirect_mismatch`.

---

## Step 5: Add "Continue with Google"

This involves two websites: Google (to create credentials) and Cognito (to use them).

### 5a. In Google Cloud Console

1. Go to [console.cloud.google.com](https://console.cloud.google.com/) and create a project called `mock-interview`.
2. Open **Google Auth Platform** (formerly "OAuth consent screen") → **Get started**. Enter an app name, your email as support contact, and choose **External** as the audience.
3. Under **Audience**, while the app is in **Testing** mode, add your own Google account as a **test user**. Only test users can log in until you publish the app.
4. Go to **Clients** → **Create client** → type **Web application**, and add:
   - **Authorized JavaScript origins:** your Cognito domain, e.g. `https://something.auth.eu-west-2.amazoncognito.com`
   - **Authorized redirect URIs:** the same domain plus `/oauth2/idpresponse`, e.g. `https://something.auth.eu-west-2.amazoncognito.com/oauth2/idpresponse`
5. Copy the **Client ID** and **Client secret**.

Notice that Google redirects to **Cognito**, not to your app. Cognito sits in the middle, which is why your app only ever deals with Cognito.

### 5b. In Cognito

1. In your user pool, open **Social and external providers** → **Add identity provider** → **Google**.
2. Paste the Google client ID and secret. Authorized scopes: `profile email openid`.
3. Map attributes: Google `email` → `email`, Google `name` → `name`.
4. Back in **App clients** → your client → **Login pages** → **Edit**, add **Google** to the identity providers, alongside the Cognito user pool.

The Google client secret now lives only inside Cognito. It never appears in your code or `.env` files.

---

## Step 6: Run the frontend

In a **third** terminal:

```powershell
cd frontend
Copy-Item .env.example .env.local
npm install
npm run dev
```

Mac/Linux: `cp .env.example .env.local`

Fill in `.env.local` with the **same** Cognito values as the backend (user pool ID, client ID, domain), then restart `npm run dev`.

**Check it worked:**

1. Open http://localhost:5173 and you'll see the five interviews **without** logging in.
2. Click **Start** on any interview. You're sent to log in, because that page is protected.
3. Try **Log in / Register**, then **Sign up** on Cognito's page, create an account and enter the email verification code. You land back on the interview you picked, with its five questions.
4. Log out, then try **Continue with Google** with the Google account you added as a test user.
5. The header shows your name. That came from `GET /users/me`, which created your user record in MongoDB on your first visit.

> Registering with email and signing in with Google using the **same** email address creates two separate Cognito users. Linking them is possible, but not needed for this project.

---

## Step 7: Commit and watch CI run

1. First, confirm your secrets won't be uploaded:

   ```powershell
   git status
   ```

   You must **not** see `backend/.env` or `frontend/.env.local` listed. You **should** see the `.env.example` files. If a real `.env` appears, stop and check your `.gitignore`.

2. Commit and push:

   ```powershell
   git add .
   git commit -m "Phase 1: foundations"
   git push
   ```

3. On GitHub, open the **Actions** tab. You'll see the **CI** workflow running three jobs:
   - **Backend - lint and test:** starts a fresh MongoDB, runs ruff and all 16 tests
   - **Frontend - type-check and build:** proves the React app compiles
   - **Backend - Docker image builds:** proves the Dockerfile works

**Check it worked:** three green ticks.

---

## Step 8: Set up dev → staging → prod

### How the environments work in this project

| | Dev | Staging | Prod |
|---|---|---|---|
| Where it runs | Your laptop (Docker Compose) | AWS | AWS |
| Database | `mock_interview_dev` (local) | Its own database | Its own database |
| Cognito user pool | `mock-interview-dev` | `mock-interview-staging` | `mock-interview-prod` |
| Who uses it | You, while building | You, final checks | Real users |
| How code gets there | You save a file | Automatically after merging to `main` | After you click **Approve** |

The key idea from `config.py`: **the code is identical everywhere; only the settings differ.** The backend is built into one Docker image, tested in staging, and then that exact same image goes to prod.

The frontend is slightly different: `VITE_` values are baked in when the app is built, so it's built separately for staging and prod, each with its own values from GitHub. That's also why `VITE_` values must never be secrets: they end up in the JavaScript anyone can read.

### Your everyday workflow

```
1. git checkout -b add-recording        (a new branch for each feature)
2. Build and test on your laptop        (dev)
3. git push, then open a pull request   (CI checks it automatically)
4. Merge when CI is green
5. Deployed to staging automatically    (added in Phase 6)
6. Check it on staging, click Approve
7. Same version deployed to prod        (added in Phase 6)
```

### Set up GitHub now

Do these in your repository's **Settings**:

1. **Protect `main`:** **Rules** (or **Branches**) → add a rule for `main` that requires a pull request before merging, and requires the **CI** checks to pass. From now on, nothing reaches `main` (and therefore staging and prod) without passing the tests.

2. **Create the environments:** **Environments** → **New environment**:
   - `staging`: no protection rules needed
   - `production`: tick **Required reviewers** and add yourself. This is the "Approve" button that guards prod.

   Each environment will hold its own variables and secrets (AWS roles, Cognito IDs, API URL), which the deploy workflow will use in Phase 6.

**Why the deployment itself comes later:** you can't deploy to staging and prod until they exist on AWS (the container service, load balancer, CloudFront, databases, and so on). In Phase 6 we'll create them with infrastructure-as-code, add a `deploy.yml` workflow that uses the environments you just made, and connect GitHub to AWS securely without storing any AWS keys in GitHub.

---

## Troubleshooting

| Problem | Likely cause and fix |
|---|---|
| `docker: command not found` or Docker errors | Docker Desktop isn't running. Start it and wait for it to finish loading. |
| `port is already allocated` | Something else uses port 8000, 27017 or 5173. Stop it, or stop old containers with `docker compose down`. |
| Frontend shows "Missing setting VITE_..." | `frontend/.env.local` is missing or incomplete. Restart `npm run dev` after editing it. |
| Browser console shows a **CORS** error | The frontend address isn't in `CORS_ORIGINS` in `backend/.env`. It must be exactly `http://localhost:5173`. |
| Cognito shows **redirect_mismatch** | Callback URL in Cognito doesn't exactly match `http://localhost:5173/` (check the trailing slash). |
| Google says **access blocked** or **not a test user** | Add your Google account as a test user (Step 5a, point 3). |
| Logged in, but `/users/me` fails with 401 | `COGNITO_USER_POOL_ID` or `COGNITO_CLIENT_ID` in `backend/.env` doesn't match the frontend's values, or you didn't restart the backend. |
| Tests fail with `ServerSelectionTimeoutError` | MongoDB isn't running. Start `docker compose up` first. |
| Code changes don't reload in Docker | Check the `volumes` line in `docker-compose.yml` and restart Compose. |

---

## What's next

- **Phase 2:** the interview screen: webcam recording and uploading videos to S3 with presigned URLs
- **Phase 3:** SQS, the worker, transcription and scoring, with live WebSocket updates
- **Phase 4:** STAR evaluation and follow-up questions
- **Phase 5:** browsing answers, embeddings, vector search and the search agent
- **Phase 6:** AWS deployment with staging and prod, and the `deploy.yml` workflow
