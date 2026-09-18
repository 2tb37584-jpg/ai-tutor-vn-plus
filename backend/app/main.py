from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.auth import router as auth_router
from app.api.students import router as students_router
from app.api.tutor import router as tutor_router
from app.core.config import get_settings

settings = get_settings()
app = FastAPI(title="AI Tutor VN API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/health")
def health():
    return {"status": "ok", "environment": settings.app_env, "ai_enabled": bool(settings.openai_api_key)}


app.include_router(auth_router, prefix="/api/v1")
app.include_router(students_router, prefix="/api/v1")
app.include_router(tutor_router, prefix="/api/v1")
