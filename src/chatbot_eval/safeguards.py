"""Small application boundaries; not a semantic truth detector or universal jailbreak filter."""
import base64
import copy
from html import escape


BLOCKED = "I couldn't validate that response against the portfolio information. Please rephrase your question."


def render_answer_html(answer):
    """Escape plain answer text for an HTML text node, not JS/CSS/URL contexts."""
    return escape(answer, quote=True)


class GuardedSession:
    """One server-owned conversation with an explicitly approved evidence registry.

    Construct a NEW instance per user session. The caller supplies trusted system
    instructions/settings; this does not authenticate arbitrary frontend payloads.
    History authenticity is not factual accuracy. Citations are not entailment.
    """
    version = 'boundaries-1.0'

    def __init__(self, provider, documents, *, max_user_chars=800, max_history_turns=6,
                 max_history_chars=8000, protected_values=()):
        if not documents or any(not isinstance(d, dict) or not isinstance(d.get('id'), str)
                                or not d['id'] or not isinstance(d.get('text'), str) for d in documents):
            raise ValueError('Approved documents require IDs and text')
        self.documents = {d['id']: copy.deepcopy(d) for d in documents}
        if len(self.documents) != len(documents):
            raise ValueError('Approved source IDs must be unique')
        if not all(isinstance(v, str) and v for v in protected_values):
            raise ValueError('Protected values must be nonempty strings')
        self.provider = provider
        self.max_user_chars = max_user_chars
        self.max_history_turns = max_history_turns
        self.max_history_chars = max_history_chars
        self.history = []
        self.audit_events = []
        self.rendered_answer_html = None
        self.model_history = []
        self.approved_source_ids = []
        self.protected_forms = [form for value in protected_values for form in
                                (value, base64.b64encode(value.encode()).decode(), value.encode().hex())]

    def __call__(self, payload):
        self.audit_events = []
        self.rendered_answer_html = None
        question = payload.get('question')
        if not isinstance(question, str) or not question.strip() or len(question) > self.max_user_chars:
            raise ValueError('Invalid question length')
        if (len(self.history) > self.max_history_turns or
                sum(len(t['question']) + len(t['answer']) for t in self.history) > self.max_history_chars):
            raise ValueError('Verified conversation exceeds limits')
        clean = copy.deepcopy(payload)
        supplied_history = payload.get('history', [])
        if supplied_history != self.history:
            self.audit_events.append('unverified_history_discarded')
        clean['history'] = copy.deepcopy(self.history)
        if not isinstance(payload.get('documents'), list):
            raise ValueError('Documents must be a list')
        approved, seen = [], set()
        for doc in payload['documents']:
            if not isinstance(doc, dict) or not isinstance(doc.get('id'), str):
                raise ValueError('Invalid source shape')
            identifier = doc['id']
            if identifier not in self.documents:
                self.audit_events.append('unapproved_source_removed')
                continue
            if doc != self.documents[identifier]:
                self.audit_events.append('modified_source_replaced_from_registry')
            if identifier not in seen:
                approved.append(copy.deepcopy(self.documents[identifier]))
                seen.add(identifier)
        clean['documents'] = approved
        self.model_history = copy.deepcopy(clean['history'])
        self.approved_source_ids = [d['id'] for d in approved]
        result = self.provider(clean)
        blocked = None
        if (not isinstance(result, dict) or set(result) != {'answer', 'citations'}
                or not isinstance(result.get('answer'), str) or not isinstance(result.get('citations'), list)
                or not all(isinstance(i, str) for i in result['citations'])):
            blocked = 'invalid_output_blocked'
        elif not set(result['citations']) <= seen:
            blocked = 'unapproved_citation_blocked'
        else:
            served = ''.join(t['answer'] for t in self.history) + result['answer']
            if any(form in served for form in self.protected_forms):
                blocked = 'protected_value_output_blocked'
        if blocked:
            self.audit_events.append(blocked)
            result = {'answer': BLOCKED, 'citations': []}
        else:
            result = copy.deepcopy(result)
        self.rendered_answer_html = render_answer_html(result['answer'])
        if self.rendered_answer_html != result['answer']:
            self.audit_events.append('html_text_escaped')
        self.history.append({'question': question, 'answer': result['answer']})
        return result
