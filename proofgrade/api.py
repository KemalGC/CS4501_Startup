from dataclasses import asdict
from pathlib import Path
import os
from time import perf_counter
from typing import Annotated

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from proofgrade.feedback import generate_feedback
from proofgrade.problems import PROBLEMS, get_problem
from proofgrade.providers import configured_provider
from proofgrade.storage import AttemptStore

STATIC = Path(__file__).parent / "static"
Step = Annotated[str, StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=256)]


class CheckRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    problem_id: str = Field(min_length=1, max_length=64)
    steps: list[Step] = Field(min_length=1, max_length=20)
    consent: bool = False
    previous_attempt_id: str | None = Field(default=None, min_length=1, max_length=64)


class CheckResponse(BaseModel):
    status: str
    first_error_step: int | None
    unsupported_step: int | None
    message: str
    hint_status: str
    hint: str | None
    provider_mode: str
    attempt_id: str | None = None


class RatingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    rating: int = Field(ge=1, le=5)


def create_app(provider=None, store=None):
    app = FastAPI(title="ProofGrade", version="0.1.0")
    provider = provider if provider is not None else configured_provider()
    if store is None and os.getenv("PROOFGRADE_STORE_ATTEMPTS", "false").lower() == "true":
        store = AttemptStore(os.getenv("PROOFGRADE_DB_PATH", "data/proofgrade.sqlite3"))

    @app.middleware("http")
    async def response_headers(request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'"
        )
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/api/config")
    def config():
        return {"provider_mode": provider.mode, "collection_enabled": store is not None}

    @app.get("/api/problems")
    def problems():
        return [{"id": item.id, "title": item.title, "equation": item.equation, "topic": item.topic}
                for item in PROBLEMS]

    @app.post("/api/check", response_model=CheckResponse)
    def check(request: CheckRequest):
        problem = get_problem(request.problem_id)
        if problem is None:
            raise HTTPException(404, "Practice problem not found.")
        started = perf_counter()
        feedback = generate_feedback(problem.equation, request.steps, problem.answer, provider)
        attempt_id = None
        if store is not None and request.consent:
            try:
                attempt_id = store.record(problem.id, feedback, provider.mode,
                                          round((perf_counter() - started) * 1000), len(request.steps),
                                          request.previous_attempt_id)
            except ValueError as error:
                raise HTTPException(400, str(error)) from error
        return {**asdict(feedback.check), "hint_status": feedback.hint_status,
                "hint": feedback.hint, "provider_mode": provider.mode, "attempt_id": attempt_id}

    @app.post("/api/attempts/{attempt_id}/rating")
    def rate(attempt_id: str, request: RatingRequest):
        if store is None or not store.rate(attempt_id, request.rating):
            raise HTTPException(404, "A saved, verified hint was not found.")
        return {"saved": True}

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(STATIC / "index.html")

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app
