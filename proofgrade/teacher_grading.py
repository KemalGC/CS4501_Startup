"""Evidence-based rubric suggestions; only teacher-approved results enter analytics."""

from dataclasses import asdict
import secrets

from proofgrade.algebra import UnsupportedInput, check_solution, parse_statement
from proofgrade.feedback import TEMPLATES, generate_feedback, verified_categories
from proofgrade.providers import answer_text


def validate_answers(assignment, answers, page_count):
    ids = [a["question_id"] for a in answers]
    if len(ids) != len(set(ids)) or set(ids) != {q["id"] for q in assignment["questions"]}:
        raise ValueError("Provide exactly one transcription for each question.")
    for answer in answers:
        page = answer["source_page"]
        if page is not None and not 1 <= page <= page_count:
            raise ValueError("A source page must refer to an uploaded page.")


def grade_question(question, answer, provider):
    steps = answer["steps"]
    category, feedback = "none", "No work was submitted."
    check = check_solution(question["equation"], steps) if steps else None
    final_correct, work_valid, unresolved = False, False, answer["unreadable"]
    try:
        for step in steps:
            parse_statement(step)
    except UnsupportedInput:
        unresolved = True
        category, feedback = "manual_review", "At least one step uses unsupported notation. Review this response manually."
    if steps and not unresolved:
        if check.status == "unsupported":
            unresolved, category = True, "manual_review"
            feedback = check.message + " Teacher review is required."
        else:
            final = parse_statement(steps[-1])
            final_correct = final.complete and final.solutions == parse_statement(question["answer"]).solutions
            has_work = any(not parse_statement(s).complete and s.replace(" ", "") != question["equation"].replace(" ", "") for s in steps)
            work_valid = check.status in ("correct", "incomplete") and has_work
            if check.status == "incorrect":
                index = check.first_error_step
                before = question["equation"] if index == 1 else steps[index - 2]
                category = verified_categories(before, steps[index - 1])[0]
                hint = generate_feedback(question["equation"], steps, question["answer"], provider)
                feedback = f"Step {index} changes the real solution set. " + (hint.hint or TEMPLATES[category]["direct"])
            elif check.status == "incomplete":
                category, feedback = "incomplete", "The checked steps are valid. State every real solution to finish."
            else:
                feedback = "The checked steps preserve the real solutions and the final answer is complete."
    if answer["unreadable"]:
        category, feedback = "manual_review", "The source is unreadable. A teacher must resolve it or grade it manually."
    criteria = []
    for criterion in question["criteria"]:
        kind = criterion["kind"]
        if unresolved or kind == "teacher_review":
            points, evidence = None, "Requires a teacher decision."
        elif kind == "final_answer":
            points = criterion["points"] if final_correct else 0
            evidence = "Final answer independently checked against the complete solution set."
        else:
            points = criterion["points"] if work_valid else 0
            evidence = "All steps must preserve solutions and include a non-final intermediate equation. Review partial credit manually."
        criteria.append({**criterion, "suggested": points, "evidence": evidence})
    return {"question_id": question["id"], "skill": question["skill"], "check": asdict(check) if check else None,
            "category": category, "feedback": feedback, "criteria": criteria,
            "needs_review": any(c["suggested"] is None for c in criteria)}


def approve_results(assignment, submission, reviewed):
    by_question = {r["question_id"]: r for r in reviewed}
    if len(by_question) != len(reviewed) or set(by_question) != {q["id"] for q in assignment["questions"]}:
        raise ValueError("Review each question exactly once.")
    results = []
    for draft in submission["results"]:
        record = by_question[draft["question_id"]]
        scores = {s["criterion_id"]: s["points"] for s in record["scores"]}
        if len(scores) != len(record["scores"]) or set(scores) != {c["id"] for c in draft["criteria"]}:
            raise ValueError("Review each rubric criterion exactly once.")
        changed = record["category"] != draft["category"] or record["feedback"] != draft["feedback"]
        for criterion in draft["criteria"]:
            score = scores[criterion["id"]]
            if not 0 <= score <= criterion["points"]:
                raise ValueError("A score is outside the rubric's point bounds.")
            changed = changed or score != criterion["suggested"]
        if changed and not record["reason"].strip():
            raise ValueError("Explain manual scores, overrides, or feedback changes.")
        results.append({**draft, "scores": scores, "earned": sum(scores.values()),
                        "possible": sum(c["points"] for c in draft["criteria"]),
                        "category": record["category"], "feedback": record["feedback"],
                        "reason": record["reason"], "overridden": changed, "needs_review": False})
    return results


def analytics(assignment, submissions):
    approved = [s for s in submissions if s["status"] == "approved"]
    questions, gaps, students = [], {}, []
    for question in assignment["questions"]:
        rows = [r for s in approved for r in s["results"] if r["question_id"] == question["id"]]
        questions.append({"question_id": question["id"], "skill": question["skill"], "reviewed": len(rows),
                          "full_credit": sum(r["earned"] == r["possible"] for r in rows),
                          "mean_percent": round(sum(100 * r["earned"] / r["possible"] for r in rows) / len(rows), 1) if rows else None})
        for row in rows:
            if row["earned"] < row["possible"]:
                gaps[question["skill"]] = gaps.get(question["skill"], 0) + 1
    for submission in approved:
        earned = sum(r["earned"] for r in submission["results"])
        possible = sum(r["possible"] for r in submission["results"])
        students.append({"student_code": submission["student_code"], "earned": earned, "possible": possible,
                         "percent": round(100 * earned / possible, 1)})
    return {"submitted": len(submissions), "approved": len(approved), "unresolved": len(submissions) - len(approved),
            "questions": questions, "gaps": [{"skill": k, "responses": v} for k, v in sorted(gaps.items())],
            "students": students}


def template_practice(skill):
    """Offline, varied equations; reference solutions are checked before returning."""
    result = []
    for index, root in enumerate(secrets.SystemRandom().sample(range(1, 10), 3)):
        factor, offset = secrets.randbelow(6) + 2, secrets.randbelow(7) + 1
        if skill == "distribution":
            equation = f"{factor}(x+{offset})={factor * (root + offset)}"
        elif skill == "quadratic":
            equation = f"x^2={root * root}"
        else:
            equation = f"{factor}x+{offset}={factor * root + offset}"
        answer = answer_text(parse_statement(equation).solutions)
        if check_solution(equation, [answer]).status != "correct":
            raise ValueError("Generated practice could not be verified.")
        result.append({"id": f"P{index + 1}", "equation": equation, "answer": answer})
    return {"skill": skill, "questions": result, "source": "checked_templates"}
