from fastapi import FastAPI
from app.routers import auth, health, jobs, applications, transcripts, plan, employer, candidate, notifications, webhooks, fake_provider
from fastapi.middleware.cors import CORSMiddleware
from app.config import settings

app = FastAPI(title="Voice Interview Platform API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(auth.router)
app.include_router(jobs.router)
app.include_router(applications.router)
app.include_router(transcripts.router)

app.include_router(plan.router)
app.include_router(employer.router)

app.include_router(candidate.router)
app.include_router(notifications.router)
app.include_router(webhooks.router)
app.include_router(fake_provider.router)