"""Browser-test server: blocked media imports and an explicit fake model transport.

This exercises the real vision request/validation path without network requests.
The returned transcript is a fixture, never handwriting-accuracy evidence.
"""

import builtins
import json
import sys

original_import = builtins.__import__


def controlled_import(name, *args, **kwargs):
    if name.split(".")[0] in ("PIL", "pypdfium2"):
        raise ImportError("DLL load failed: An Application Control policy has blocked this file.")
    return original_import(name, *args, **kwargs)


builtins.__import__ = controlled_import

import httpx
import uvicorn

from proofgrade.api import create_app
from proofgrade.teacher_ai import OpenAITeacherModel


def fake_model(request):
    body = json.loads(request.content)
    content = body["input"][0]["content"]
    if "answers" in body["text"]["format"]["schema"]["properties"]:
        assert any(part["type"] == "input_image" and part["image_url"].startswith("data:image/png;base64,")
                   for part in content)
        questions = json.loads(content[0]["text"])["questions"]
        assert questions == [{"id": "Q1", "equation": "2(x+3)=10"}]
        result = {"answers": [{"question_id": "Q1", "steps": ["2x+3=10", "2x=7"],
                               "source_page": 1, "unreadable": False, "note": "Synthetic test transcription"}]}
    else:
        result = {"questions": [{"equation": "2(x+3)=10", "answer": "x=2"},
                                {"equation": "3(x-1)=12", "answer": "x=5"},
                                {"equation": "4(x+2)=28", "answer": "x=5"}]}
    return httpx.Response(200, json={"status": "completed", "output": [
        {"type": "message", "content": [{"type": "output_text", "text": json.dumps(result)}]}]})


model = OpenAITeacherModel("synthetic-key", "synthetic-model", httpx.Client(transport=httpx.MockTransport(fake_model)))
uvicorn.run(create_app(teacher_model=model), host="127.0.0.1", port=int(sys.argv[1]), access_log=False)
