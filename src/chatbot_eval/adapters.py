"""Adapters own transport mapping; the runner never assumes a framework."""
import json
import time
from dataclasses import asdict
from urllib.request import Request as UrlRequest, urlopen
from urllib.parse import urlsplit
from urllib.error import HTTPError, URLError
from .models import Request, Response, Document


class AdapterError(RuntimeError):
    pass


def normalize(value):
    if isinstance(value, Response):
        return value
    if not isinstance(value, dict) or not isinstance(value.get("answer"), str):
        raise AdapterError("Response must contain a text answer")
    docs = value.get("retrieved_documents")
    try:
        return Response(
            answer=value["answer"], citations=value.get("citations", []),
            retrieved_documents=None if docs is None else [Document(**d) for d in docs],
            mode=value.get("mode", "unknown"), metadata=value.get("metadata", {}),
        )
    except (TypeError, ValueError) as exc:
        raise AdapterError("Invalid normalized response") from exc


class CallableAdapter:
    def __init__(self, function):
        self.function = function

    def ask(self, request: Request) -> Response:
        start = time.perf_counter()
        response = normalize(self.function(request))
        response.latency_ms = (time.perf_counter() - start) * 1000
        return response


class HttpAdapter:
    """POST question/history; receive answer/citations/optional retrieved_documents.

    Use only with endpoints you own or have permission to test. No automatic retries.
    Credentials can be supplied in headers; headers are never added to reports.
    """
    def __init__(self, endpoint, *, timeout=20, headers=None):
        parsed = urlsplit(endpoint)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("endpoint must be an HTTP(S) URL")
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        self.endpoint, self.timeout = endpoint, timeout
        self.headers = {"Content-Type": "application/json", **(headers or {})}

    def encode(self, request):
        return {"question": request.question, "history": [asdict(t) for t in request.history]}

    def decode(self, value):
        return normalize(value)

    def ask(self, request):
        start = time.perf_counter()
        req = UrlRequest(self.endpoint, json.dumps(self.encode(request)).encode(), self.headers, method="POST")
        try:
            with urlopen(req, timeout=self.timeout) as handle:
                value = json.loads(handle.read())
            response = self.decode(value)
        except HTTPError as exc:
            raise AdapterError(f"HTTP {exc.code}") from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise AdapterError("Endpoint unavailable or timed out") from exc
        except (ValueError, TypeError, KeyError) as exc:
            raise AdapterError("Invalid endpoint response") from exc
        response.latency_ms = (time.perf_counter() - start) * 1000
        return response


class PortfolioAdapter(HttpAdapter):
    """Maps the portfolio's existing public HTTP contract, not its private code."""
    def __init__(self, endpoint, **kwargs):
        parsed = urlsplit(endpoint)
        headers = {"Origin": f"{parsed.scheme}://{parsed.netloc}", **kwargs.pop("headers", {})}
        super().__init__(endpoint, headers=headers, **kwargs)

    def encode(self, request):
        if len(request.question) > 800 or len(request.history) > 6:
            raise ValueError("Portfolio accepts 800-character questions and at most six turns")
        return {"message": request.question, "history": [t.question for t in request.history],
                "turns": [{"question": t.question, "answer": t.answer,
                           "projectIds": list(t.project_ids)} for t in request.history]}

    def decode(self, value):
        if not isinstance(value, dict) or not isinstance(value.get("answer"), str):
            raise AdapterError("Invalid portfolio response")
        sources = value.get("sources", [])
        if not isinstance(sources, list) or any(not isinstance(s, dict) or not isinstance(s.get("url"), str) for s in sources):
            raise AdapterError("Invalid portfolio sources")
        return Response(value["answer"], [s["url"] for s in sources],
                        mode=value.get("mode", "unknown"),
                        metadata={"context": value.get("context", {})})
