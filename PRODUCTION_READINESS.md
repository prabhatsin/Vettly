# Production Readiness Audit: Voice Interview Platform (Vettly)

Scope: the whole repo (`api/`, `agent/`, `web/`, infrastructure files) at commit `73db92a`. Each item lists the **gap**, **why it matters**, a **concrete fix**, **effort** (S ≤ 1 day, M ≤ 1 week, L > 1 week), and **priority** (P0 must-have, P1 should-have, P2 nice-to-have). Paths are cited where a claim comes from the code. Anything marked **(inferred)** was not directly visible in the code.

---

## Table of contents

1. [What already exists (strengths)](#1-what-already-exists-strengths)
2. [Security](#2-security)
3. [Reliability](#3-reliability)
4. [Voice-specific](#4-voice-specific)
5. [Data, privacy and compliance](#5-data-privacy-and-compliance)
6. [Testing and evals](#6-testing-and-evals)
7. [Observability](#7-observability)
8. [Deployment](#8-deployment)
9. [Product and UX](#9-product-and-ux)
10. [Prioritised roadmap](#10-prioritised-roadmap)
11. [Top 5 to fix before showing a recruiter](#11-top-5-to-fix-before-showing-a-recruiter)

---

## 1. What already exists (strengths)

Keep these. Several are better than typical portfolio projects.

- **Authorisation in the service layer, returning 404 for "missing or not yours".** `EmployerService._own_job` / `own_application` (`api/app/services/employer.py:39-50`), `ApplicationService.get_for_candidate`, `TranscriptService.read`, `NotificationService.mark_read`. Covered by cross-tenant tests (`test_other_employer_gets_404_everywhere`, `test_other_users_get_404`).
- **Argon2 password hashing** (`api/app/core/security.py:8`). `employer_id` and `candidate_id` always come from the token, never the request body.
- **Internal endpoints use a constant-time shared-key check** (`api/app/routers/transcripts.py:24`).
- **An atomic interview state machine in Redis Lua** with idempotent operations (`agent/interview_state.py`), plus code-level guards against LLM misbehaviour (`agent/interview_tools.py`).
- **A locked, audited application status machine** (`api/app/services/status_machine.py`).
- **A reliable scoring queue** (BLMOVE + processing list + dedupe set) (`api/app/services/scoring_queue.py`).
- **Grounded scoring:** evidence quotes are checked against candidate turns, scoring retries with feedback, coverage thresholds give `insufficient_data`, and every report carries an advice note (`api/app/services/scoring.py`).
- **An idempotent payment flow** with an `Idempotency-Key`, commit-before-provider-call, an HMAC-verified webhook and row locks (`api/app/services/payments.py`).
- **Structured LLM output** validated by Pydantic for plans and scores. Prompt-injection guidance in the plan, interviewer and scorer prompts.
- **Upload validation:** a 5 MB cap and a `%PDF` magic-byte check (`api/app/core/storage.py`).
- **About 213 tests** in total (155 API, 58 agent).

---

## 2. Security

| # | Gap | Why it matters | Suggested fix | Effort | Priority |
|---|---|---|---|---|---|
| S1 | **Candidate PII is committed to git**: 15 résumé PDFs in `api/uploads/`, plus `agent/agent.log`, which contains raw candidate speech (`lk.pii.user_transcript`). `.gitignore` excludes neither. | Personal data in source control can't be revoked once pushed. This is a GDPR/DPDP-style exposure, and a reviewer will spot it. | `git rm --cached -r api/uploads agent/agent.log`. Add `api/uploads/`, `*.log` to `.gitignore`. Rewrite history with `git filter-repo` before any public push. Keep a synthetic `api/tests/fixtures/sample.pdf` instead. | S | **P0** |
| S2 | **`/fake-provider/intents/{id}/confirm` has no authentication and is always mounted** (`api/app/routers/fake_provider.py`, `api/app/main.py:27`). | Anyone who knows an intent id can mark a payment succeeded. | Mount the dev-only routers only when `settings.env == "dev"`. Add an `ENV` setting. | S | **P0** |
| S3 | **The webhook secret has an in-code default** `"dev-webhook-secret"` (`api/app/config.py:35`). | If the env var is missing in production, webhooks are signed with a public secret. | Remove the default. Fail at startup when it is unset outside dev. | S | **P0** |
| S4 | **No rate limiting** on `/auth/login`, `/auth/register`, `/jobs/{id}/apply`, `/interview-token`, `/rescore`, `/matches/recompute`. | Credential stuffing. Cost abuse: each token request triggers a Gemini prewarm, and rescore and recompute call Gemini. | `slowapi` or a Redis token bucket per IP and per user. For example: 5 logins/min per IP plus per email, 3 interview tokens/hour per application, 1 rescore/min. | M | **P0** |
| S5 | **Unlimited interview retakes.** `interview_token` doesn't check `application.status` or `job.is_active` (`api/app/routers/applications.py:82-101`). | Candidates can redo interviews after being scored, shortlisted or offered. That overwrites evidence (see R1) and costs money. | Allow tokens only when the status is `applied` (or `interviewed` with an unfinished Redis state) and the job is active. Store an `interview_attempts` row with a max count. | S | **P0** |
| S6 | **JWT in `localStorage`** (`web/lib/api.ts:3-6`), 60-minute access token, **no refresh, logout or revocation**. | Any XSS steals a working token. A stolen token can't be revoked. | Move to an httpOnly, Secure, SameSite=Lax cookie with a short access token (10–15 min) and a rotating refresh token stored hashed in DB. Add a `jti` denylist in Redis for logout. If cookies are used, add CSRF protection. | M | P1 |
| S7 | **Self-assigned employer role** at registration (`web/app/register/page.tsx`, `RegisterRequest.role`). | Anyone can see candidate PII for jobs they post. Spam job posts. | Email verification. An employer org with domain verification or admin approval. Separate signup flows. | M | P1 |
| S8 | **No email verification, password reset or lockout.** `TODDO.txt` lists it. | Account takeover, fake accounts. | Signed one-time tokens (itsdangerous or DB-stored) for verify and reset. Progressive lockout after failed logins. | M | P1 |
| S9 | **SSE token sent in the query string** (`api/app/routers/notifications.py:35`). | Tokens end up in proxy and access logs and in browser history. | Issue a short-lived (60 s), single-purpose stream ticket from an authenticated POST, or use cookie auth. | S | P1 |
| S10 | **One static `INTERNAL_API_KEY`** shared by every agent, with no rotation. `/internal/*` is on the public API. | One leak exposes every plan (with the résumé excerpt) and allows writing any transcript, which triggers scoring. | Put `/internal/*` on a private network or a separate internal service. Support two keys during rotation. Better: a short-lived signed JWT per room, minted with the LiveKit token and carried in room metadata. | M | P1 |
| S11 | **Upload hardening.** pypdf parses untrusted PDFs synchronously in the request (`api/app/core/parsing.py`). There is no malware scan, no page or time limit, and files sit on local disk. | PDF bombs or slow PDFs tie up workers. Malware gets passed to employers if a download is added later. | Parse in a worker with a timeout and a page cap (for example 20). Run ClamAV or a cloud scanner. Store in S3/GCS with server-side encryption and serve via pre-signed URLs. | M | P1 |
| S12 | **CORS** allows `*` methods and headers (`api/app/main.py:8-13`). The origin list comes from config, which is fine. | Low risk today with no credentials. It matters once cookies are added (S6). | Name the methods and headers explicitly. Set `allow_credentials=True` only with exact origins. | S | P2 |
| S13 | **No security headers** on the web app or API. | Clickjacking and XSS impact. | Next.js `headers()` with CSP (allow LiveKit wss), `X-Frame-Options`, `Referrer-Policy`, HSTS at the edge. | S | P1 |
| S14 | **Audit log covers application status only** (`application_status_events`). | Nothing records who read reports or transcripts, rubric edits, rescore requests, or job edits. | An `audit_events` table (actor, action, resource, ip, at) written from services. Required for hiring compliance. | M | P1 |
| S15 | **Unpinned API dependencies** (`api/requirements.txt` pins only `google-genai`). `pytest` ships in the production image. | Non-reproducible builds, supply-chain drift. | Use `pip-tools`/`uv lock` with hashes. Split `requirements-dev.txt`. Run Dependabot plus `pip-audit` and `npm audit` in CI. | S | P1 |
| S16 | **`.env.example` lists 3 of ~25 variables.** | People guess, and a secret ends up in the wrong file. | Complete `.env.example` with placeholders and comments (see the walkthrough, §6). Use a secrets manager in production. | S | P1 |
| S17 | **The LiveKit token gives the default publish/subscribe grants** (`api/app/core/livekit.py:20`). | A candidate could publish video, data or screen share **(inferred: SDK defaults)**. | Set `can_publish_sources=[MICROPHONE]` and `can_publish_data=False`. Shorten the TTL to about 30 min. Add room metadata for the agent. | S | P2 |

---

## 3. Reliability

| # | Gap | Why it matters | Suggested fix | Effort | Priority |
|---|---|---|---|---|---|
| R1 | **A rejoin overwrites the transcript.** The agent posts only `session.history` (`agent/interviewer.py:343`). The API deletes and reinserts (`api/app/repositories/transcript.py:15-25`). | Any dropped call loses the first part of the interview. Scoring and replay see a partial transcript. | Add `session_id` (the LiveKit job id) to `transcript_entries`, and make the save endpoint idempotent per `(application_id, session_id)`. Scoring and replay merge sessions by time. Optionally, also flush turns to Redis as they happen. | M | **P0** |
| R2 | **Abandoned and degraded interviews are never scored.** `ended` only becomes true through Redis state (`interviewer.py:256-270`). No-plan, no-Redis and dropped-call sessions save with `ended=false` and nothing ever queues them. | The employer sees "not scored" forever, and the candidate is stuck in `interviewed`. | A sweeper job: if the application is `interviewed` and has had no session for X minutes (or the Redis TTL is about to expire), queue scoring with `reason=abandoned`. In degraded mode, send `ended=true` on shutdown when the candidate spoke. | M | **P0** |
| R3 | **Notes and summaries live only in Redis with a 6 h TTL** (`agent/interview_state.py:4`). | The interviewer's notes are lost, and they can't be used for scoring or audit. | Include `notes` and `summaries` in the transcript payload and persist them (a JSONB column on a new `interview_sessions` table). | S | P1 |
| R4 | **The scoring worker is safe only as a single instance.** `requeue_stale` moves **all** processing ids (`scoring_queue.py:38`). `enqueue` does SADD then LPUSH non-atomically. | Two workers will double-process. A crash between SADD and LPUSH leaves the id deduped forever and never queued. | Per-worker processing lists or Redis Streams with `XAUTOCLAIM`. Make enqueue a single Lua script or `MULTI`. Or adopt Arq or Celery. | M | P1 |
| R5 | **No timeouts on Gemini calls** (`plan_generator.py`, `scoring_runner.py:35`, `embedding.py:18`). SDK and network errors aren't retried in `PlanGenerator` (only `ValidationError`/`ValueError`/`TypeError`). | A hung call blocks the worker, or the request thread for `matches/recompute`. Network blips become 500s. | Set an HTTP timeout on `genai.Client`. Use `tenacity` with exponential backoff and jitter on 429/5xx. Map failures to `PlanGenerationFailed`. | S | P1 |
| R6 | **Plan generation runs in FastAPI `BackgroundTasks`** in the API process, triggered on apply **and on every token request** (`routers/applications.py:49, 98`). | Lost if the API restarts. Duplicate Gemini calls under concurrency (a race between prewarm and the agent fetch; the DB constraint saves the row, not the cost). | Move it onto the worker queue with dedupe. Generate once on apply. On token request, only check that the plan exists. | M | P1 |
| R7 | **`ScoringJob` sets status `scored` before scoring finishes** (`scoring_runner.py:76-77`). | A failed scoring run leaves the application `scored` with a failed report, so the employer can shortlist on no data. | Advance to `scored` only after `status="done"`. Show failed reports in the UI with a retry button. | S | P1 |
| R8 | **`/matches/recompute` embeds every résumé synchronously in the request** (`services/matching.py:54-61`). | Slow, times out for big jobs, no partial progress. | Queue it as a background job. Embed each résumé once on apply. Use pgvector. | M | P2 |
| R9 | **Redis outage behaviour.** The agent falls back to list mode (no state, no scoring; see R2). The API's `events.publish` is best-effort, which is good. Enqueue failure is logged but not retried. The worker retries its connection. | Silent loss of scoring jobs. | A transactional outbox: write a `scoring_jobs` row in Postgres in the same transaction as the transcript save, and have a relay push it to Redis. The sweeper in R2 covers what's left. | M | P1 |
| R10 | **Postgres outage.** No retry on the agent's transcript POST (`interviewer.py:356-365`). On failure the transcript is lost. | Interview content lost. | Retry with backoff (3–5 attempts). On final failure, write the payload to Redis `transcript:pending:{id}` for a replay job. | S | P1 |
| R11 | **LLM provider down during the call.** No LLM fallback (only TTS has one, and both TTS options are Gnani). No STT fallback. | A Cerebras or Gnani outage ends every live interview. | LiveKit `llm.FallbackAdapter` and `stt.FallbackAdapter` with a second provider. Use a different vendor for the TTS fallback. | M | P1 |
| R12 | **Frontend reconnect.** `RoomEvent.Disconnected` just shows "ended" and offers "Start again" (`web/app/interview/[id]/page.tsx:71, 96`). There's no handling for `Reconnecting`/`Reconnected`. | A network blip looks like the end of the interview. | Handle the reconnecting states with a banner. Auto-retry `connect` with a fresh token. Show "resuming…" when Redis state exists. | S | P1 |
| R13 | **The health check always returns 200** even when degraded, uses its own engine, and ignores LiveKit and the worker (`api/app/routers/health.py`). | Load balancers can't route around a broken instance. | Separate `/livez` (process up) and `/readyz` (DB + Redis, 503 on failure). Report worker heartbeat and queue depth. | S | P1 |
| R14 | **Lazy offer expiry** happens only when someone reads the offer (`hiring.py:78`). | Notifications go out late or never. Payments stay held. | A periodic job (cron or the worker) that expires due offers. | S | P2 |
| R15 | **No payment reconciliation** if a webhook never arrives. | Payments stuck `pending`. | A job that queries the provider for stale pending intents. | S | P2 (test mode only) |
| R16 | **Repositories commit internally** (`repositories/*.py`). Multi-step services such as `hiring.make_offer` rely on commit ordering. | It's hard to reason about atomicity, and a partial failure can leave half-done work. | Unit of work: services own `commit()`; repositories only `flush()`. | M | P2 |

---

## 4. Voice-specific

| # | Gap | Why it matters | Suggested fix | Effort | Priority |
|---|---|---|---|---|---|
| V1 | **No latency measurement.** Nothing collects end-of-utterance delay, LLM TTFT, TTS TTFB or tool round-trip time. | Voice quality depends on response time. Without data, tuning is guesswork. | Subscribe to `session.on("metrics_collected")` and log `EOUMetrics`, `LLMMetrics`, `TTSMetrics` per turn **(inferred API names; check the 1.8 docs)**. Export p50/p95. Budget, for example: endpointing ≤ 1.3 s, LLM TTFT ≤ 400 ms, TTS TTFB ≤ 300 ms, so the first audio arrives about 2 s after the candidate stops. | M | **P0** |
| V2 | **No consent, recording or AI-interviewer notice** before the mic turns on (`web/app/interview/[id]/page.tsx:73-74`). | Many jurisdictions require disclosure of AI use in hiring and consent to processing (for example NYC LL 144, the EU AI Act's high-risk category, Illinois AI Video Interview Act **(inferred legal applicability; get counsel)**). | A pre-interview screen covering: AI interviewer, what is captured (audio → transcript), retention, human review, an accommodation request option, and a checkbox. Store `consent_at` and the policy version on the application. | S | **P0** |
| V3 | **Fixed endpointing** (1.3–2.5 s) with no semantic turn detector. | Thinking pauses still get cut off, and quick answers wait at least 1.3 s. | Try LiveKit's turn-detector model or a dynamic mode. A/B test on the false-cutoff rate (from logs: a note saved right after a turn followed by more speech) against response latency. | M | P1 |
| V4 | **The code-level skip regex anchors on the end of the turn** (`SKIP_END_RE`, `interviewer.py:61`). | An answer ending "…and then move on" or "…next" triggers a skip. | Require a short utterance (≤ 4 words) for a code skip. Otherwise let the LLM decide. Add eval cases. | S | P1 |
| V5 | **Stages split by position, not category** (`agent/session_data.py:18`). The plan prompt doesn't require an order. | The behavioral agent may get technical questions, and the stage prompt contradicts the question. | Sort plan questions by category in `PlanService` before storing, or compute ranges from categories. | S | P1 |
| V6 | **Poor audio handling.** No noise suppression, no low-confidence STT handling, no mic-level check before starting. | Bad transcripts lead to bad scores, which is unfair to candidates on poor connections. | Browser: `noiseSuppression`/`echoCancellation` constraints and a mic test meter. Agent: when STT confidence is low or the transcript is very short, ask the candidate to repeat. Flag the report "audio quality issues". BVC noise cancellation on LiveKit Cloud **(inferred availability)**. | M | P1 |
| V7 | **Silence handling.** There's no "are you still there?" after long silence. The timer keeps counting. | An idle candidate uses up the time and the cost. | A user-away timeout (LiveKit `user_away_timeout`/user state events **(inferred)**): prompt once, then end with `reason=no_response`. | S | P2 |
| V8 | **Cost controls.** A 20-minute cap and 1 follow-up exist. There's no per-candidate attempt cap (S5), no per-tenant budget and no usage logging. | Abuse and runaway spend. | Log STT seconds, TTS characters and LLM tokens per room (from metrics). Daily budgets per employer. The attempt cap. | M | P1 |
| V9 | **The TTS fallback uses the same vendor** (two Gnani models). | It doesn't protect against a Gnani outage. | Second vendor in `FallbackAdapter`. Keep the voice consistent, or tell the candidate when the voice changes. | S | P2 |
| V10 | **`close_when_quiet` waits at most 30 s,** and the shutdown callbacks rely on `close_redis` reading `ended` before `save_transcript` (`interviewer.py:257-272, 338-340`). | Depends on callback order; fragile. | Read `ended` once in `save_transcript` before closing Redis, and register the transcript save first. | S | P2 |
| V11 | **Accessibility of the voice format.** There's no text-input alternative and no option for extra time. | Excludes candidates with speech or hearing impairments and creates accommodation obligations. | A text-chat mode using the same tools, plus an extended time limit when an accommodation is requested. | L | P2 |

---

## 5. Data, privacy and compliance

| # | Gap | Why it matters | Suggested fix | Effort | Priority |
|---|---|---|---|---|---|
| D1 | **Migrations are never exercised in tests** (`api/tests/conftest.py:24` uses `create_all`). The enum downgrade is incomplete (`de8eb88d3c64`). | Schema drift between models and migrations goes unnoticed until deploy. | CI step: `alembic upgrade head` on an empty DB, then `alembic check` (autogenerate diff is empty), then downgrade and upgrade. Run tests against the migrated schema. | S | **P0** |
| D2 | **No backups or restore procedure.** | Data loss. | Managed Postgres with PITR. A nightly logical dump to object storage. A quarterly restore drill. Versioned buckets for résumés. | S | P1 |
| D3 | **Missing indexes for real queries.** | Slow employer dashboards as data grows. | `applications(job_id, status)`, `notifications(user_id, created_at DESC)`, `application_status_events(application_id, created_at)`, `offers(expires_at) WHERE status='pending'`. | S | P2 |
| D4 | **No retention or deletion.** Résumés, transcripts, reports and embeddings are kept forever. No account deletion or data export. | Privacy laws (GDPR/DPDP) require purpose limitation, deletion and access rights. | A retention policy (for example 12 months after the job closes). A purge job that deletes files and rows. `DELETE /me` plus an export endpoint. CASCADE FKs already help. | M | P1 |
| D5 | **PII in logs.** The agent logs transcripts at DEBUG (`lk.pii.*` in `agent.log`). Notification "emails" are logged with their content. | Logs are a common leak vector. | Set the production log level to INFO. Use LiveKit's PII redaction setting **(inferred)**. Scrub emails in log formatters. | S | P1 |
| D6 | **Third-party data processing.** Résumés go to Gemini, and audio and text go to Gnani and Cerebras. | Needs DPAs, data-residency checks, and disclosure to candidates. | Document the subprocessors. Choose regions and no-training options. Put it in the consent screen (V2). | S | P1 |
| D7 | **Bias and fairness are not measured.** The rubric and report don't use demographics, which is good, and there's an advice note. But there's no adverse-impact monitoring, and STT accuracy may vary by accent. | Automated hiring tools face bias-audit requirements (for example NYC LL 144 **(inferred applicability)**). | Track selection rates by voluntary self-ID group (stored separately, never sent to the scorer). Run an annual bias audit. Measure STT word error rate by accent. Strip names and gender cues from the résumé excerpt before scoring. | L | P1 |
| D8 | **Human-in-the-loop is implied but not enforced.** Nothing stops a pipeline that rejects candidates straight from the score. | Regulatory and ethical risk. | Require a human action for reject and shortlist (already the case: only the employer role can do them). Show the advice note prominently. Record the reviewer id (already in the status events). Never auto-reject. | S | P1 |
| D9 | **Candidate access to results.** Candidates can read their transcript (`GET /applications/{id}/transcript`) but there's no UI, and they can't see or contest a report. | Transparency and the right to explanation. | A candidate page showing the transcript and the status timeline, plus a request-review contact. | M | P2 |
| D10 | **Free-string statuses** on `offers.status` and `payments.status` with no DB constraint. | Typos become invalid states. | Postgres enums or `CHECK` constraints via migration. | S | P2 |

---

## 6. Testing and evals

| # | Gap | Why it matters | Suggested fix | Effort | Priority |
|---|---|---|---|---|---|
| T1 | **No CI at all** (no `.github/`). | Regressions ship. Reviewers check this first. | GitHub Actions jobs: API (service containers `postgres:16`, `redis:7`; `alembic upgrade head`; `pytest`), agent (`pytest`), web (`npm ci && npm run lint && npm run build`). Required before merge. | S | **P0** |
| T2 | **Two agent tests fail** (`test_long_note_rejected`, `test_followup_reason_validated`, `agent/tests/test_interview_tools.py`). The code was changed to truncate and forgive (`interview_tools.py:150, 262`). | A red suite trains everyone to ignore it. | Update the tests to assert truncation and the default reason. | S | **P0** |
| T3 | **Dev dependencies aren't declared.** `agent/requirements-dev.txt` contains pytest.ini text. `fakeredis` and `pytest-asyncio` aren't listed. `api/requirements.txt` lacks `fakeredis`, which `test_scoring_flow.py` uses. `python-dotenv` arrives only as a transitive dependency of pydantic-settings. | A fresh clone can't run the tests. | Real `requirements-dev.txt` files for both packages. | S | **P0** |
| T4 | **No tests for `interviewer.py`** (entrypoint, turn guard, `_skip_in_code`, handoff wiring, transcript save payload). | The most complex runtime path is untested. | Unit-test `on_user_turn_completed` with a fake session. Use LiveKit Agents' text-mode test harness (`AgentSession` with a mock LLM) for handoff and end **(inferred availability in 1.8)**. Test the `save_transcript` payload against a mocked HTTP server. | M | P1 |
| T5 | **No simulated-candidate evals** (`evals/eval.py` is notes only). | Prompt and model changes silently break behaviour. | A text-mode harness: a persona LLM (strong, weak, rambling, prompt-injector, skipper, silent) talks to Iris through the same tools on fakeredis. Rule checks: every question asked in order, ≤ 1 follow-up, no praise or feedback, no tool text spoken, ends correctly. LLM-judge checks: question mentions a résumé item, stays on topic. Track pass rates per commit. | L | P1 |
| T6 | **Scoring consistency isn't measured.** | Recruiters need stable scores. | A golden set of about 30 labelled transcripts. Re-score 5× and report the score std-dev per criterion, the recommendation flip rate, and agreement with human labels (Cohen's κ / Spearman). Fail CI when these drift. | M | P1 |
| T7 | **No end-to-end UI tests.** | Login → apply → interview → report breaks without notice. | Playwright with the agent stubbed (or a fake LiveKit room). Cover the happy paths for both roles. | M | P2 |
| T8 | **No load tests** for concurrent interviews. | Unknown capacity per agent worker. | Run N synthetic rooms with LiveKit's load tester (`lk load-test` **(inferred)**) and measure CPU per session and latency. | M | P2 |
| T9 | **Frontend has no type-checked API client.** `lib/types.ts` is hand-maintained (for example `Application.candidate_email`, which `/applications/mine` doesn't return). | Drift between API and UI. | Generate TS types from `/openapi.json` (`openapi-typescript`) in CI. | S | P2 |

---

## 7. Observability

| # | Gap | Why it matters | Suggested fix | Effort | Priority |
|---|---|---|---|---|---|
| O1 | **Unstructured logs.** The API borrows the `uvicorn.error` logger. There are no request ids, and nothing correlates logs across API, agent and worker. | You can't trace one interview end to end. | JSON logging (`structlog`). A request-id middleware. Carry `application_id`, `room`, `job_id` and `session_id` as context everywhere. | M | P1 |
| O2 | **No error tracking.** | Exceptions in background tasks and the worker go unnoticed. | Sentry SDK in the API, worker, agent and Next.js, with PII scrubbing. | S | P1 |
| O3 | **No metrics.** | Can't see queue depth, score failure rate, plan latency or interview completion rate. | Prometheus (or OTel metrics): `scoring_queue_depth`, `scoring_duration`, `report_status_total{status}`, `plan_generation_seconds`, `interviews_started/completed/abandoned`, voice latency (V1). Grafana dashboard. | M | P1 |
| O4 | **No tracing.** | Can't see where latency goes in a turn or in scoring. | OpenTelemetry for FastAPI, SQLAlchemy, httpx and aiohttp. LiveKit Agents emits OTel spans **(inferred)**. Export to Tempo/Honeycomb. | M | P2 |
| O5 | **No alerts.** | Outages are discovered by users. | Alerts on: readiness failing, queue depth > N for 10 min, report failure rate > 10%, interview abandon rate spike, provider 5xx rate, p95 voice latency over budget. | S | P1 |
| O6 | **No cost tracking.** | You can't price the product. | Per-interview usage record (STT s, TTS chars, LLM tokens, Gemini tokens for plan and scoring) stored on `interview_sessions`. Weekly cost report. | M | P1 |

---

## 8. Deployment

| # | Gap | Why it matters | Suggested fix | Effort | Priority |
|---|---|---|---|---|---|
| P1 | **Compose runs only the infrastructure.** No services for api, worker, agent or web. No web Dockerfile. | Not reproducible, and a demo needs five terminals. | Extend `docker-compose.yml` with `api`, `worker` (same image, `python -m app.worker`), `agent` and `web`. Add `depends_on: condition: service_healthy`. Add a `migrate` one-shot service. | S | **P0** (for the demo) |
| P2 | **Dockerfiles run as root, are single stage, and have no HEALTHCHECK** (`api/Dockerfile`, `agent/Dockerfile`). | Container-escape blast radius, bigger images, no orchestrator health. | Multi-stage build, `USER app`, pinned base digest, `HEALTHCHECK` on `/livez`, `--no-cache-dir` (already done). Pre-download the Silero model at build time (`python interviewer.py download-files` **(inferred CLI)**). | S | P1 |
| P3 | **Migrations aren't part of the deploy.** | Schema mismatch on release. | A dedicated migrate job before rollout. Expand/contract pattern for breaking changes. | S | P1 |
| P4 | **No environments or config separation.** | Dev defaults (fake provider, `--dev` LiveKit, webhook secret) leak into production. | An `ENV` setting with dev, staging and prod. Settings validation per environment. Separate LiveKit projects and keys. | S | P1 |
| P5 | **Agent worker scaling isn't defined.** `num_idle_processes=1` (`interviewer.py:47`). | Cold starts under load. Unknown sessions per pod. | Run the agent as a Deployment autoscaled on active jobs or CPU. Set `load_threshold` and idle processes from load tests. Use graceful drain on deploy (LiveKit workers finish active jobs before exiting **(inferred)**). | M | P1 |
| P6 | **The API isn't stateless.** Uploads are on local disk. BackgroundTasks do LLM work. | Can't run multiple replicas behind a load balancer. | Object storage (S11). Move background work to the queue (R6). | M | P1 |
| P7 | **No rollback strategy.** | Bad releases can't be undone quickly. | Immutable image tags (git SHA), blue/green or rolling deploys with automatic rollback on readiness failure, and backward-compatible migrations. | M | P2 |
| P8 | **No TLS or ingress config.** LiveKit `--dev` binds 0.0.0.0 with `node-ip 127.0.0.1`. | Production WebRTC needs TURN/TLS and a public IP. | LiveKit Cloud, or a properly configured self-hosted cluster with TURN over TLS 443. API behind HTTPS ingress. | M | P1 |

---

## 9. Product and UX

| # | Gap | Why it matters | Suggested fix | Effort | Priority |
|---|---|---|---|---|---|
| U1 | **The hiring flow has no UI**: shortlist, reject, offer, fund, candidate offers, notifications and SSE, matches, rubric, must-haves and history are API-only (walkthrough §4). | The best backend work can't be shown in a demo. | Employer applicant page: status timeline (`/history`), shortlist and reject buttons, offer form, fund button plus a simulated "pay" page calling `/fake-provider/.../confirm`. Candidate "Offers" page with accept and decline. A notification bell using `EventSource`. | M | P1 |
| U2 | **"Start interview" shows for every status** and "Start again" appears after the end (`web/app/applications/page.tsx:37-42`, `interview/[id]/page.tsx:96`). | Confusing, and enables retakes (S5). | Show by status: "Start", "Resume", "Completed – under review", or the offer state. | S | **P0** |
| U3 | **Loading and error states are thin.** Pages return `null` while auth loads. `applications/page.tsx` has no `.catch`. Rescore waits a fixed 20 s and then fetches once (`employer/applications/[id]/page.tsx:31`). | Blank screens and stale data. | Skeletons. Error boundaries. Poll the report until `status !== "pending"`, or listen on SSE. | S | P1 |
| U4 | **No pre-interview checks**: mic permission, device picker, level meter, browser support, what to expect. | Candidates start with a muted or wrong mic, and the interview fails. | A lobby page with a mic test, device select, instructions and consent (V2). Handle `NotAllowedError` with clear guidance. | S | P1 |
| U5 | **No progress indicator during the interview** (question n of N, time left). | Candidates feel lost. (Iris's prompt rules forbid saying how many questions remain, so show it visually.) | Agent publishes participant attributes (`stage`, `question_index`, `remaining_seconds`), and the UI renders them. | S | P2 |
| U6 | **Accessibility.** Inputs have no labels (placeholders only). No `aria-live` on captions. Colour-only status cues. | WCAG failures, screen-reader users blocked. | `<label>` for every input. `aria-live="polite"` on the caption log. Visible focus states. Contrast check. | S | P1 |
| U7 | **Mobile.** The layout is simple and responsive (`max-w-2xl`, `md:grid-cols-2`). Not tested on mobile Safari audio (autoplay and `startAudio`). | iOS needs a user gesture to start audio **(inferred LiveKit/iOS behaviour)**. | Call `room.startAudio()` from the start-button handler. Test on iOS and Android. | S | P1 |
| U8 | **Empty states exist but are minimal** ("No open jobs yet.", "No applicants yet."). | Fine for now. | Add calls to action (post a job, browse jobs). | S | P2 |
| U9 | **No real email notifications** (only `logger.info("EMAIL (dev)…")`, `services/notifications.py:28`). | Candidates miss offers and status changes. | A provider (SES, Postmark, Resend) via the worker queue, with templates and unsubscribe. | M | P1 |
| U10 | **Branding and metadata are default.** The `<title>` is "Create Next App" (`web/app/layout.tsx:16`). The README's homepage health badges no longer exist. | A first impression with recruiters. | Set the title, favicon and landing page. Update the README. | S | **P0** (for the demo) |
| U11 | **Employers can't download or view the résumé.** | They need it to review alongside the report. | An authorised `GET /employer/applications/{id}/resume` (pre-signed URL once on object storage). | S | P2 |

---

## 10. Prioritised roadmap

### 1 day

1. **Privacy cleanup (S1).** Untrack `api/uploads/` and `agent/agent.log`, update `.gitignore`, and plan the history rewrite.
2. **CI green (T1–T3).** Fix the 2 stale agent tests, write real `requirements-dev.txt` files, and add a GitHub Actions workflow with Postgres and Redis service containers running `alembic upgrade head` and both pytest suites, plus `next build`.
3. **Lock dev surfaces (S2, S3).** Add an `ENV` flag, gate `fake_provider` and the default webhook secret behind it, and fail fast on missing secrets.
4. **Interview integrity, quick part (S5, U2).** Status-gate `/interview-token` and the "Start interview" button.
5. **Scoring status (R7).** Advance to `scored` only on success.
6. **Demo polish (U10, S16, P1).** Complete `.env.example`, update the README (alembic, worker, agent steps), set the page title, and add compose services for api, worker and web.

### 1 week

1. **Durable transcripts (R1, R3).** Add an `interview_sessions` table with session id, notes, summaries, usage, `ended_reason` and consent. Store transcripts per session. Merge them for scoring and replay.
2. **Abandoned and degraded scoring (R2, R9, R10).** Sweeper job, outbox row for scoring, retries on the agent's transcript POST.
3. **Consent and lobby (V2, U4).** Disclosure, consent record, mic test, device picker.
4. **Hiring UI (U1).** Shortlist, reject, offer, fund, candidate offers, notification bell over SSE (with S9's stream ticket).
5. **Rate limiting (S4)** and Gemini timeouts and retries (R5).
6. **Voice metrics (V1).** Per-turn latency logging and a simple dashboard. Fix stage ordering by category (V5) and the skip-regex length guard (V4).
7. **Observability basics (O1, O2, O5).** JSON logs with `application_id`, Sentry, readiness endpoint (R13).

### 1 month

1. **Auth hardening (S6–S8).** httpOnly cookie sessions with refresh rotation, email verification, password reset, employer verification.
2. **Eval harness (T5, T6).** Simulated candidates, rule and judge checks, a scoring-consistency golden set, regression gates in CI.
3. **Scale-out (R4, R6, P5, P6, S11).** Proper queue (Streams or Arq) with multiple workers, plan generation on the queue, object storage for résumés with scanning, agent autoscaling from load tests (T8).
4. **Provider resilience (R11, V9).** Cross-vendor LLM, STT and TTS fallbacks. Cost tracking and budgets (O6, V8).
5. **Compliance (D2, D4–D8, S14).** Backups and PITR, retention and deletion, subprocessor disclosure, an audit log of reads and edits, bias monitoring plan.
6. **Deployment (P2–P4, P7, P8).** Hardened images, migrate job, staging environment, rollback, production LiveKit with TURN/TLS.

---

## 11. Top 5 to fix before showing a recruiter

1. **Remove the candidate PII from the repo.** Untrack and purge `api/uploads/*.pdf` (15 résumés) and `agent/agent.log` (raw transcripts), and gitignore them (S1). It's the first thing a careful reviewer will notice.
2. **Make one interview equal one complete transcript.** Gate the token endpoint and the "Start interview" button by status, and stop rejoins from overwriting earlier turns (S5, U2, R1). Otherwise the headline feature has a visible data-integrity bug.
3. **Get the tests green in CI.** Fix the 2 stale agent tests, declare the dev dependencies, and add a GitHub Actions workflow with Postgres and Redis that runs the migrations and both suites (T1–T3, D1). A green badge backs up the "213 tests" claim.
4. **Make the demo run with one command and look finished.** Compose services for api, worker, agent and web, a complete `.env.example`, an accurate README, a real page title, and a consent and mic-check screen before the interview (P1, S16, U10, V2, U4).
5. **Close the obvious security holes and show the hiring flow.** Gate `/fake-provider` and the default webhook secret by environment, add login rate limiting (S2–S4), and build a minimal shortlist → offer → accept UI so the status machine and idempotent payments can be seen (U1).
