# Vettly system design: notes

Sources: `api/` and `agent/` in this repo, `docker-compose.yml`, and the frontend repo (`Voice_ai_frontend/src`). Anything not read directly from code is marked **(inferred)**.

Files:
- `hero.svg` / `hero.png` (1600×900): the simple diagram for the X post.
- `detailed.svg` / `detailed.png` (2400×1350): every component, grouped into zones.

The SVGs embed their fonts (Instrument Serif, Inter, JetBrains Mono as base64 WOFF2), so they render the same anywhere. The PNGs were rendered with headless Chrome at device scale factor 2.

---

## Components

**Client (Next.js 16, React 19, `livekit-client`)**
- Candidate pages: jobs, apply with a PDF résumé, interview, offers.
- Employer dashboard: candidates per job, report, replay with evidence quotes, rubric editor, matches, shortlist, reject, offer, fund.
- `lib/api.ts`: `fetch` wrapper that sends `Authorization: Bearer <JWT>`. A 401 clears the session and sends the user to `/login`.
- `lib/token.ts`: the JWT is kept in `localStorage` (`vettly_token`).
- `lib/use-interview-room.ts`: mic test, then `POST /applications/{id}/interview-token`, then `room.connect(url, token)`, then the mic is enabled. It waits up to 20 s for a participant with `isAgent`. It reads `lk.agent.state` (listening / thinking / speaking) from participant attributes. When the agent leaves, the interview is over.
- `lib/events.tsx`: one shared `EventSource` to `/events/stream?token=…` (SSE) for live notifications.

**API (FastAPI, `api/app`)**
- Routers: `auth`, `jobs`, `applications` (apply, interview-token), `transcripts` and `plan` (internal routes, guarded by `X-Internal-Key`), `employer` (candidates, report, replay, rescore, rubric, matches, must-haves, history, shortlist, reject, offer, fund), `candidate` (offers accept/decline), `notifications` (list, read, SSE stream), `webhooks` (payments), `fake_provider` (test-mode payment intent).
- `core/livekit.py`: signs a LiveKit access token for room `interview-{application_id}`, `room_join` grant, 1 h TTL. No LiveKit server call is made; it is local JWT signing.
- `services/plan_generator.py`: Gemini structured output that produces 8–10 questions (résumé verification, technical depth, behavioural). `plan_prewarm` runs it in a FastAPI `BackgroundTask` on apply and on token request, so the agent rarely waits.
- `services/status_machine.py`: the only place an application's status may change: applied → interviewed → scored → shortlisted → offered → accepted/declined, plus rejected. Each move is checked by role (system / employer / candidate) and logged to `application_status_events`.
- `services/matching.py` + `embedding.py`: ranking = 0.6 × interview score + 0.4 × résumé–job cosine similarity (Gemini embeddings), with must-have keyword filters.
- `services/notifications.py`: saves a notification row, publishes it to Redis `user:{id}`, and logs a dev "email".
- Résumés: PDF only, max 5 MB, saved to local disk (`uploads/`), text extracted with `pypdf`.

**Real-time voice (`agent/`)**
- LiveKit server: `livekit/livekit-server --dev` in docker-compose (local).
- Agent worker: `AgentServer` with `@server.rtc_session()`. It sets no `agent_name`, so LiveKit dispatches it to every new room automatically **(inferred from LiveKit's default dispatch behaviour)**. `prewarm` loads Silero VAD once per process and keeps 1 idle process.
- `AgentSession`: Silero VAD → Gnani STT (`en-IN`) → Cerebras LLM (`qwen-3.8-27b`, no parallel tool calls) → Gnani TTS. TTS is a `FallbackAdapter` over timbre-v2.5 "Kaveri" and timbre-v3.0 "Shivani".
- TTS text transforms strip bracketed or JSON tool text, banned filler phrases, markdown and emoji.
- Turn handling: fixed endpointing with a 1.3–2.5 s delay. Interruptions need at least 2 words and 0.6 s. A false interruption resumes after 1.5 s. Preemptive generation is off.
- Stage agents: `ScreenerAgent` → `TechnicalAgent` → `BehavioralAgent` (all subclasses of `StageAgent`). Questions are split 25% / 50% / 25% (`split_ranges`).
- Tools (`interview_tools.py`): `next_question`, `record_answer_note`, `request_followup` (max 1 per question), `repeat_question`, `skip_question`, `end_interview`, plus `stage_done` on non-final stages.
- Code guards: a skip command at the end of a turn is handled in code (`StopResponse`), leftover STT words after a skip are dropped, and the stage handoff and interview end are triggered in code after the last note is saved.
- Timer: counts connected seconds into Redis every 5 s. The default limit is 20 min, with wrap-up 3 min before the end.
- On shutdown: posts the transcript (user/assistant messages, excluding internal `[continue]` prompts) to `/internal/applications/{id}/transcript`.

**Data**
- Postgres 16 (docker-compose). Tables: users, jobs, applications, interview_plans, transcript_entries, rubrics, interview_reports, candidate_matches, offers, payments, notifications, application_status_events. Alembic migrations.
- Redis 7 (docker-compose), used for three things:
  1. **Live interview state**: hash `interview:{id}` (current_index, followups_used, awaiting_answer, active_seconds, wrapup, stage, status) plus `:notes` and `:summaries`. All changes go through atomic Lua scripts. 6 h TTL.
  2. **Scoring job queue**: `scoring:queue` (list), `scoring:processing` (list), `scoring:pending` (set, to skip duplicates). Jobs are taken with `BLMOVE` and removed with `ack`. Unfinished jobs are requeued when the worker starts.
  3. **Pub/sub**: channel `user:{id}`, relayed to the browser over SSE.

**Background jobs**
- Scoring worker: `python -m app.worker`, a single loop over the Redis queue.
- `ScoringJob`: loads the transcript, merges consecutive same-speaker entries into turns, loads the job's rubric (or the default 4 criteria), sets the status to `scored`, and runs the orchestrator.
- `ScoringOrchestrator`: one `CriterionScorer` per criterion (technical_depth ×1.5, problem_solving ×1.5, communication, resume_consistency), at most 4 running in parallel. Each scorer is a Gemini call with JSON output at temperature 0.
- Evidence check (`verify_evidence`): after lowercasing and stripping punctuation, each quote must appear in a **candidate** turn and be at least 3 words long (or be the whole turn). A wrong turn number is fixed if the quote matches exactly one turn. If no quote passes, the scorer retries (up to 3 attempts) with feedback. If it still fails, the criterion is marked `unverified` and gets no score.
- `ReportBuilder`: weighted mean over verified criteria only. Coverage below 50% gives `insufficient_data`. Otherwise ≥3.8 is hire, ≥2.8 is maybe, and anything lower is no_hire. Every report carries a note that this is advice for a human reviewer, not a decision.

**External providers**
- Gnani: STT and TTS. Cerebras: the live LLM. Google Gemini: plan generation, scoring and embeddings.

**Deployment, as far as the repos show**
- `api/Dockerfile` (uvicorn) and `agent/Dockerfile` (`python interviewer.py start`).
- docker-compose runs Postgres, Redis and LiveKit for local development only.
- The API runs on Railway. This comes from the frontend repo's `CLAUDE.md` and `.env.example`, not from any infra config.
- Not defined in either repo: where the agent worker, the scoring worker, production LiveKit, the frontend, Postgres and Redis are hosted. The scoring worker has no Dockerfile or compose service of its own; running it from the API image with `python -m app.worker` is **(inferred)**.

---

## Main flows in plain language

1. **Apply.** The candidate uploads a PDF résumé. The API stores it, extracts the text, and starts building a question plan with Gemini in the background.
2. **Start the interview.** The browser asks the API for a room token. The API signs a LiveKit token for room `interview-{application_id}` and starts the plan build again in case it isn't ready.
3. **Join the room.** The browser connects to LiveKit over WebRTC and turns on the mic. LiveKit dispatches the agent worker into the room.
4. **Set up the agent.** The agent reads the application id from the room name, fetches the plan from the API's internal route, and creates (or resumes) the interview state in Redis.
5. **Talk.** Iris greets the candidate. Each turn runs VAD → STT → LLM → TTS. The LLM gets questions one at a time from tools that read and write Redis.
6. **Hand off.** When the Screener's questions are done, the code builds a stage summary and hands the same live call to the Technical agent, then to the Behavioral agent. The candidate stays in the same call with the same voice.
7. **Reconnect.** If the connection drops, a rejoin resumes from the Redis state ("welcome back") instead of starting over.
8. **Finish.** After the last note, or when time runs out, Iris says goodbye and the session closes. The agent posts the transcript.
9. **Score.** The API saves the transcript and, if the interview ended properly, queues a scoring job. The worker scores each criterion, drops any quote the candidate didn't say, and saves the report.
10. **Review and hire.** The employer sees the ranked candidates, the report and a replay where each evidence quote is linked to its transcript turn. They shortlist, send an offer and fund it (test-mode payments). The candidate gets live notifications over SSE.

---

## 5 design decisions worth explaining

1. **Three agents, one call: handoff instead of three separate calls.** Each stage has its own instructions and toolset, but they share one `AgentSession` and room. The handoff passes the stage summaries and the Redis-backed progress, so the next agent doesn't re-ask topics. It is triggered in code once the last note of a stage is saved, so the LLM can't forget to hand off or hand off too early.

2. **Interview progress lives in Redis, not in the LLM's context.** Question index, follow-up count, connected time and stage are kept in one Redis hash, and every change is an atomic Lua script. The LLM can't skip ahead, ask a second follow-up, or end early, because the tools refuse. A dropped connection resumes exactly where it left off. If Redis is down, the agent falls back to a simple single-agent interviewer without tools.

3. **Evidence-checked scoring.** Every score must cite quotes copied word for word from a candidate turn. The code checks each quote against the transcript. A score with no valid quotes is retried and then marked unverified, and the overall result is computed only from verified criteria, with a coverage threshold. The replay uses the same merged turn numbers as the scorer, so the employer can click from a claim to the moment the candidate said it.

4. **Three separate processes for three workloads.** The API handles short request/response. The agent holds long real-time media sessions and scales by concurrent calls. Scoring is slow, bursty LLM work. They talk only over HTTP internal routes (with a shared key) and Redis, so a scoring backlog never slows a live interview. The queue uses `BLMOVE` into a processing list, so a worker crash doesn't lose jobs.

5. **Latency choices on the live path.** Silero VAD is loaded once per process and an idle process is kept warm. The plan is pre-generated when the candidate applies and again when they request a token, so the agent's plan fetch is usually a database read. The live LLM is a fast Cerebras-hosted model and TTS has a fallback voice. Endpointing waits 1.3–2.5 s, so candidates who pause to think aren't cut off, and short noises don't count as interruptions.

---

## Alt text

**hero.png**
> Vettly system design. A candidate's browser talks to a Next.js app, which calls a FastAPI backend with Postgres. The browser joins a LiveKit room over WebRTC. LiveKit dispatches an agent worker, the AI interviewer Iris, which runs one live call through three stages, Screener, Technical and Behavioral, handing off between them and sharing state in Redis. The agent fetches its question plan from FastAPI and sends back the transcript. FastAPI queues a scoring worker, which produces an evidence report with quotes checked against the transcript. The report feeds an employer dashboard with replay and hiring. The live voice path is drawn in green and the data path in black.

**detailed.png**
> Detailed Vettly architecture in six zones. Client: interview room using livekit-client, candidate pages, employer dashboard, an API client sending a JWT, and live events over server-sent events. Real-time voice: a LiveKit server and an agent worker running VAD, speech-to-text, LLM and text-to-speech, with turn detection and interruption settings, a handoff chain from Screener to Technical to Behavioral, guarded tools, and shared state. External providers: Gnani for speech-to-text and text-to-speech, Cerebras for the LLM, and Google Gemini for plans, scoring and embeddings. API: FastAPI with internal routes for plan and transcript, auth, job applications, interview token, plan generator, employer routes, hiring and offers, notifications and a status machine. Data: Redis holding live interview state, the scoring job queue and pub/sub channels, and Postgres holding the main tables. Background jobs: a queue worker, a scoring job, an orchestrator running four criterion scorers in parallel, an evidence check that keeps only quotes found in candidate turns with up to three retries, and a report builder. Numbered markers 1 to 8 show the interview-start sequence from token request to scoring.

---

## Not verifiable from the code

- Automatic agent dispatch: inferred from LiveKit's default behaviour when no `agent_name` is set. There is no explicit dispatch call in either repo.
- Hosting for the agent worker, scoring worker, frontend, production LiveKit, Postgres and Redis: not defined. Only the API's Railway hosting is mentioned, and only in frontend docs.
- How the scoring worker is run in production: no Dockerfile or compose service exists for it.
- The Gemini model used for scoring: `scoring_model` falls back to `plan_model` (`gemini-3.8-flash` by default). The live values come from env, which I did not read.
