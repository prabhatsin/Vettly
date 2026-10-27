from fastapi import FastAPI
from app.routers import health,auth

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