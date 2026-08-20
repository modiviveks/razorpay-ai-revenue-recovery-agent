"""Main FastAPI Application Entrypoint."""

import contextlib
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from database import init_db
from config import settings
from api.webhook import router as webhook_router
from api.events import router as events_router
from api.dashboard import router as dashboard_router

@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    """Handles startup and shutdown events."""
    print("[Server] Initializing database tables...")
    init_db()
    print("[Server] Database initialized successfully.")
    yield
    print("[Server] Shutting down...")

app = FastAPI(
    title="Razorpay AI Revenue Recovery Agent",
    description="Automated payment recovery, error classification, and auditable actions.",
    version="1.0.0",
    lifespan=lifespan
)

# Keep browser access limited to configured dashboard origins.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
app.include_router(dashboard_router)
app.include_router(webhook_router)
app.include_router(events_router)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
