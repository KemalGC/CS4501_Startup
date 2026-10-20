"""Authenticated teacher API. The practice API remains independent."""

from collections import defaultdict, deque
import csv
import io
import os
import sqlite3
from threading import Lock
import time
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import PlainTextResponse

from proofgrade.teacher_grading import analytics, approve_results, grade_question, template_practice, validate_answers
from proofgrade.teacher_models import AssignmentInput, ApprovalInput, LoginInput, PracticeInput, SubmissionInput, TranscriptInput
from proofgrade.teacher_store import MissingRecord, RevisionConflict
from proofgrade.feedback import ProviderUnavailable

COOKIE = "proofgrade_teacher"
DATA_KEYS = ("answers", "results", "page_count", "extraction", "message", "approved_at")


def record_data(record):
    return {k: record[k] for k in DATA_KEYS if k in record}


def build_teacher_router(store, hint_provider, model=None):
    async def csrf(request: Request):
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            if request.headers.get("x-proofgrade-request") != "1":
                raise HTTPException(403, "Use the teacher workspace to submit this request.")
            origin = request.headers.get("origin")
            if origin:
                supplied, expected = urlsplit(origin), request.url
                if supplied.scheme != expected.scheme or supplied.netloc != expected.netloc:
                    raise HTTPException(403, "Cross-origin requests are not accepted.")

    router = APIRouter(prefix="/api/teacher", dependencies=[Depends(csrf)])
    attempts, rate_lock = defaultdict(deque), Lock()

    def teacher(request: Request):
        user = store.session(request.cookies.get(COOKIE))
        if not user:
            raise HTTPException(401, "Sign in to your teacher workspace.")
        return user["id"]

    @router.get("/session")
    def session(request: Request):
        user = store.session(request.cookies.get(COOKIE))
        return {"authenticated": bool(user), "username": user["username"] if user else None,
                "hint_mode": hint_provider.mode, "vision_mode": "openai" if model else "disabled"}

    @router.post("/login")
    def login(body: LoginInput, request: Request, response: Response):
        host, now = request.client.host if request.client else "unknown", time.monotonic()
        with rate_lock:
            for key in list(attempts):
                while attempts[key] and attempts[key][0] < now - 60:
                    attempts[key].popleft()
                if not attempts[key]:
                    del attempts[key]
            if len(attempts[host]) >= 10 or len(attempts) > 1000:
                raise HTTPException(429, "Too many sign-in attempts. Try again in a minute.")
            attempts[host].append(now)
        token = store.login(body.username, body.password)
        if token is None:
            raise HTTPException(401, "Incorrect username or password.")
        secure = request.url.scheme == "https" or os.getenv("PROOFGRADE_SECURE_COOKIES", "false") == "true"
        response.set_cookie(COOKIE, token, httponly=True, secure=secure, samesite="strict", max_age=8 * 3600, path="/api/teacher")
        return {"username": body.username}

    @router.post("/logout")
    def logout(request: Request, response: Response, owner=Depends(teacher)):
        store.logout(request.cookies[COOKIE])
        response.delete_cookie(COOKIE, path="/api/teacher")
        return {"signed_out": True}

    @router.get("/assignments")
    def assignments(owner=Depends(teacher)):
        return store.assignments(owner)

    @router.post("/assignments", status_code=201)
    def create_assignment(body: AssignmentInput, owner=Depends(teacher)):
        return store.create_assignment(owner, body.model_dump())

    @router.get("/assignments/{assignment_id}")
    def assignment(assignment_id: str, owner=Depends(teacher)):
        return store.assignment(owner, assignment_id)

    @router.delete("/assignments/{assignment_id}")
    def delete_assignment(assignment_id: str, owner=Depends(teacher)):
        store.delete_assignment(owner, assignment_id)
        return {"deleted": True}

    @router.get("/assignments/{assignment_id}/submissions")
    def submissions(assignment_id: str, owner=Depends(teacher)):
        return store.submissions(owner, assignment_id)

    @router.post("/assignments/{assignment_id}/submissions", status_code=201)
    def create_submission(assignment_id: str, body: SubmissionInput, owner=Depends(teacher)):
        return store.create_submission(owner, assignment_id, body.student_code)

    @router.get("/submissions/{submission_id}")
    def submission(submission_id: str, owner=Depends(teacher)):
        return store.submission(owner, submission_id)

    @router.delete("/submissions/{submission_id}")
    def delete_submission(submission_id: str, owner=Depends(teacher)):
        store.delete_submission(owner, submission_id)
        return {"deleted": True}

    @router.get("/submissions/{submission_id}/history")
    def history(submission_id: str, owner=Depends(teacher)):
        return store.events(owner, submission_id)

    @router.post("/submissions/{submission_id}/transcript")
    def confirm_transcript(submission_id: str, body: TranscriptInput, owner=Depends(teacher)):
        record = store.submission(owner, submission_id)
        if body.revision != record["revision"]:
            raise RevisionConflict()
        assignment = store.assignment(owner, record["assignment_id"])
        answers = [a.model_dump() for a in body.answers]
        validate_answers(assignment, answers, record["page_count"])
        mapped = {a["question_id"]: a for a in answers}
        results = [grade_question(q, mapped[q["id"]], hint_provider) for q in assignment["questions"]]
        data = record_data(record) | {"answers": answers, "results": results,
                                      "message": "Review each rubric score and approve the result."}
        data.pop("approved_at", None)
        return store.update_submission(owner, submission_id, body.revision, "grading_draft", data, "transcript_confirmed")

    @router.post("/submissions/{submission_id}/approve")
    def approve(submission_id: str, body: ApprovalInput, owner=Depends(teacher)):
        record = store.submission(owner, submission_id)
        if record["status"] != "grading_draft":
            raise HTTPException(409, "Confirm the transcription and review a draft before approving.")
        if body.revision != record["revision"]:
            raise RevisionConflict()
        assignment = store.assignment(owner, record["assignment_id"])
        results = approve_results(assignment, record, [q.model_dump() for q in body.questions])
        data = record_data(record) | {"results": results, "approved_at": time.time(),
                                     "message": "Teacher approved. Included in class summaries and exports."}
        return store.update_submission(owner, submission_id, body.revision, "approved", data, "grade_approved")

    @router.get("/assignments/{assignment_id}/analytics")
    def class_summary(assignment_id: str, owner=Depends(teacher)):
        assignment = store.assignment(owner, assignment_id)
        return analytics(assignment, store.submissions(owner, assignment_id))

    @router.get("/students/{student_code}/progress")
    def progress(student_code: str, class_name: str, owner=Depends(teacher)):
        rows = []
        for assignment in store.assignments(owner):
            if assignment["class_name"] != class_name:
                continue
            for record in store.submissions(owner, assignment["id"]):
                if record["status"] == "approved" and record["student_code"] == student_code:
                    earned, possible = sum(r["earned"] for r in record["results"]), sum(r["possible"] for r in record["results"])
                    rows.append({"assignment": assignment["title"], "earned": earned, "possible": possible,
                                 "percent": round(100 * earned / possible, 1), "approved_at": record["approved_at"]})
        return sorted(rows, key=lambda r: r["approved_at"])

    @router.get("/assignments/{assignment_id}/grades.csv")
    def export_grades(assignment_id: str, owner=Depends(teacher)):
        assignment = store.assignment(owner, assignment_id)
        summary = analytics(assignment, store.submissions(owner, assignment_id))
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["student_code", "earned", "possible", "percent"])
        for row in summary["students"]:
            code = row["student_code"]
            if code.startswith(("=", "+", "-", "@")):
                code = "'" + code
            writer.writerow([code, row["earned"], row["possible"], row["percent"]])
        return Response(output.getvalue(), media_type="text/csv",
                        headers={"Content-Disposition": 'attachment; filename="approved-grades.csv"'})

    @router.get("/submissions/{submission_id}/feedback.txt")
    def export_feedback(submission_id: str, owner=Depends(teacher)):
        record = store.submission(owner, submission_id)
        if record["status"] != "approved":
            raise HTTPException(409, "Approve the result before exporting feedback.")
        lines = [f"ProofGrade feedback — {record['student_code']}", ""]
        for result in record["results"]:
            lines.extend([f"{result['question_id']}: {result['earned']}/{result['possible']}", result["feedback"], ""])
        return PlainTextResponse("\n".join(lines), headers={"Content-Disposition": 'attachment; filename="feedback.txt"'})

    @router.post("/assignments/{assignment_id}/practice", status_code=201)
    def create_practice(assignment_id: str, body: PracticeInput, owner=Depends(teacher)):
        assignment = store.assignment(owner, assignment_id)
        summary = analytics(assignment, store.submissions(owner, assignment_id))
        if body.skill not in {g["skill"] for g in summary["gaps"]}:
            raise HTTPException(409, "Approve a result with a gap in this skill before creating targeted practice.")
        try:
            practice = model.practice(body.skill) if model else template_practice(body.skill)
        except ProviderUnavailable as error:
            raise HTTPException(503, str(error)) from error
        return store.create_practice(owner, assignment_id, practice)

    @router.get("/assignments/{assignment_id}/practice")
    def practices(assignment_id: str, owner=Depends(teacher)):
        return store.practices(owner, assignment_id)

    @router.post("/practice/{practice_id}/approve")
    def approve_practice(practice_id: str, owner=Depends(teacher)):
        return store.practice(owner, practice_id, approve=True)

    @router.get("/practice/{practice_id}/questions.txt")
    def export_practice(practice_id: str, owner=Depends(teacher)):
        record = store.practice(owner, practice_id)
        if not record["approved"]:
            raise HTTPException(409, "Review the answer keys and approve the practice set first.")
        lines = [f"Practice: {record['skill']}", "Solve each equation. Show your work.", ""]
        lines.extend(f"{q['id']}. {q['equation']}\n" for q in record["questions"])
        return PlainTextResponse("\n".join(lines), headers={"Content-Disposition": 'attachment; filename="targeted-practice.txt"'})

    return router, teacher


def register_teacher_errors(app):
    @app.exception_handler(MissingRecord)
    async def missing(request, error):
        from fastapi.responses import JSONResponse
        return JSONResponse({"detail": "Record not found in your workspace."}, status_code=404)

    @app.exception_handler(RevisionConflict)
    async def conflict(request, error):
        from fastapi.responses import JSONResponse
        return JSONResponse({"detail": "This submission changed. Reload it before saving."}, status_code=409)

    @app.exception_handler(sqlite3.IntegrityError)
    async def duplicate(request, error):
        from fastapi.responses import JSONResponse
        return JSONResponse({"detail": "This student code already has a submission for the assignment."}, status_code=409)
