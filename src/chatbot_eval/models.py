from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass(frozen=True)
class Turn:
    question: str
    answer: str
    project_ids: tuple[str, ...] = ()

    def __post_init__(self):
        if not isinstance(self.question, str) or not self.question.strip() or not isinstance(self.answer, str):
            raise ValueError("history requires a non-empty question and text answer")
        if not isinstance(self.project_ids, (list, tuple)) or not all(isinstance(p, str) for p in self.project_ids):
            raise ValueError("project_ids must be a sequence of strings")


@dataclass(frozen=True)
class Request:
    question: str
    history: tuple[Turn, ...] = ()

    def __post_init__(self):
        if not isinstance(self.question, str) or not self.question.strip():
            raise ValueError("question must be non-empty text")
        if not isinstance(self.history, (tuple, list)) or not all(isinstance(t, Turn) for t in self.history):
            raise ValueError("history must contain Turn objects")


@dataclass(frozen=True)
class Document:
    id: str
    text: str

    def __post_init__(self):
        if not isinstance(self.id, str) or not self.id or not isinstance(self.text, str):
            raise ValueError("document requires a non-empty id and text")


@dataclass
class Response:
    answer: str
    citations: list[str] = field(default_factory=list)
    retrieved_documents: list[Document] | None = None
    latency_ms: float = 0
    mode: str = "unknown"
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not isinstance(self.answer, str):
            raise ValueError("answer must be text")
        if not isinstance(self.citations, list) or not all(isinstance(c, str) for c in self.citations):
            raise ValueError("citations must be a list of strings")
        if self.retrieved_documents is not None and (not isinstance(self.retrieved_documents, list) or not all(isinstance(d, Document) for d in self.retrieved_documents)):
            raise ValueError("retrieved_documents must be a list of Document objects or None")
        if not isinstance(self.mode, str) or not isinstance(self.metadata, dict):
            raise ValueError("mode must be text and metadata must be an object")

    def to_dict(self):
        return asdict(self)
