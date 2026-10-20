"""Bounded records for the teacher workflow; all model output uses these schemas."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from proofgrade.algebra import UnsupportedInput, parse_statement

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=256)]
Identifier = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{1,40}$")]
Skill = Literal["linear", "distribution", "quadratic"]
Category = Literal["none", "distribution", "missing_root", "extra_root", "equivalence", "incomplete", "manual_review"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Criterion(StrictModel):
    id: Identifier
    label: Text
    kind: Literal["final_answer", "valid_work", "teacher_review"]
    points: int = Field(ge=1, le=20)


class Question(StrictModel):
    id: Identifier
    equation: Text
    answer: Text
    skill: Skill
    criteria: list[Criterion] = Field(min_length=1, max_length=5)

    @model_validator(mode="after")
    def validate_key(self):
        try:
            original, answer = parse_statement(self.equation), parse_statement(self.answer)
        except UnsupportedInput as error:
            raise ValueError(f"Unsupported question or answer key: {error}") from error
        if not answer.complete or original.solutions != answer.solutions:
            raise ValueError("The answer key must state every real solution of the question.")
        if len({c.id for c in self.criteria}) != len(self.criteria):
            raise ValueError("Rubric criterion IDs must be unique within each question.")
        return self


class AssignmentInput(StrictModel):
    title: Text
    class_name: Text
    questions: list[Question] = Field(min_length=1, max_length=5)

    @model_validator(mode="after")
    def unique_questions(self):
        if len({q.id for q in self.questions}) != len(self.questions):
            raise ValueError("Question IDs must be unique.")
        return self


class Answer(StrictModel):
    question_id: Identifier
    steps: list[Text] = Field(max_length=20)
    source_page: int | None = Field(ge=1, le=5)
    unreadable: bool
    note: str = Field(max_length=500)


class SubmissionInput(StrictModel):
    student_code: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{1,40}$")]


class TranscriptInput(StrictModel):
    revision: int = Field(ge=1)
    answers: list[Answer] = Field(min_length=1, max_length=5)
    confirmed: Literal[True]


class CriterionScore(StrictModel):
    criterion_id: Identifier
    points: int = Field(ge=0, le=20)


class ReviewedQuestion(StrictModel):
    question_id: Identifier
    scores: list[CriterionScore] = Field(min_length=1, max_length=5)
    category: Category
    feedback: str = Field(max_length=1500)
    reason: str = Field(max_length=1000)


class ApprovalInput(StrictModel):
    revision: int = Field(ge=1)
    confirmed: Literal[True]
    questions: list[ReviewedQuestion] = Field(min_length=1, max_length=5)


class RevisionInput(StrictModel):
    revision: int = Field(ge=1)


class PracticeInput(StrictModel):
    skill: Skill


class LoginInput(StrictModel):
    username: str = Field(min_length=3, max_length=64, pattern=r"^[A-Za-z0-9_.-]+$")
    password: str = Field(min_length=1, max_length=128)
