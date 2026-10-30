"""Transparent lexical demo: intentionally not an LLM and not a security system.

No access to test cases or expected answers. Documents are developer-controlled;
this naive retriever illustrates misses and inadequate multi-question coverage.
"""
import json
import re
from .dataset import data_path
from .models import Response, Document


def respond(request):
    docs = json.loads(data_path("documents.json").read_text(encoding="utf-8"))
    query = request.question.lower()
    if re.search(r"ignore.*(instruction|rule)|pretend|invent|system prompt|secret|password", query):
        return Response("I cannot invent claims or disclose private information.", mode="demo-refusal")
    if re.search(r"salary|home address|phone number|married|employer|rust|javascript|guarantee", query):
        return Response("The supplied documents do not establish that information.", mode="demo-unknown")
    if re.search(r"^(and|what about|how about|why|which).*\b(it|that|its)\b", query) and request.history:
        query += " " + request.history[-1].question.lower()
    tokens = set(re.findall(r"[a-z0-9+]+", query))
    ranked = sorted(((len(tokens & set(d["keywords"])), d) for d in docs), key=lambda item: item[0], reverse=True)
    selected = [d for score, d in ranked[:2] if score]
    if not selected:
        return Response("The supplied documents do not establish that information.", mode="demo-unknown", retrieved_documents=[])
    return Response(" ".join(d["text"] for d in selected), [d["id"] for d in selected],
                    [Document(d["id"], d["text"]) for d in selected], mode="demo-retrieval")
