from dataclasses import asdict
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from proofgrade.feedback import generate_feedback
from proofgrade.problems import PROBLEMS, get_problem
from proofgrade.providers import configured_provider

STATIC = Path(__file__).parent / "static"
Step = Annotated[str, StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=256)]


class CheckRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    problem_id: str = Field(min_length=1, max_length=64)
    steps: list[Step] = Field(min_length=1, max_length=20)


class CheckResponse(BaseModel):
    status: str
    first_error_step: int | None
    unsupported_step: int | None
    message: str
    hint_status: str
    hint: str | None
    provider_mode: str


def create_app(provider=None):
    app = FastAPI(title="ProofGrade", version="0.1.0")
    provider = provider if provider is not None else configured_provider()

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
        return {"provider_mode": provider.mode}

    @app.get("/api/problems")
    def problems():
        return [{"id": item.id, "title": item.title, "equation": item.equation, "topic": item.topic}
                for item in PROBLEMS]

    @app.post("/api/check", response_model=CheckResponse)
    def check(request: CheckRequest):
        problem = get_problem(request.problem_id)
        if problem is None:
            raise HTTPException(404, "Practice problem not found.")
        feedback = generate_feedback(problem.equation, request.steps, problem.answer, provider)
        return {**asdict(feedback.check), "hint_status": feedback.hint_status,
                "hint": feedback.hint, "provider_mode": provider.mode}

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(STATIC / "index.html")

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app
