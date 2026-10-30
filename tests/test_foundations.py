import json
import threading
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import pytest
from chatbot_eval import Request, Response, Turn, CallableAdapter, HttpAdapter, PortfolioAdapter
from chatbot_eval.adapters import AdapterError
from chatbot_eval.dataset import load_cases, data_path, verify_freeze
from chatbot_eval.demo import respond
from chatbot_eval.runner import run
from chatbot_eval.cli import main


@pytest.fixture
def endpoint():
    seen = []
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            seen.append((body, self.headers.get('Origin')))
            if self.path == '/error':
                self.send_response(429); self.end_headers(); return
            self.send_response(200); self.end_headers()
            value = {'answer': 'Known answer', 'citations': ['doc-a']}
            if self.path == '/portfolio':
                value = {'answer': 'Known answer', 'sources': [{'url': '/resume.html'}], 'mode': 'facts', 'context': {'documentIds': ['skills']}}
            self.wfile.write(b'not json' if self.path == '/invalid' else json.dumps(value).encode())
        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    yield f'http://127.0.0.1:{server.server_port}', seen
    server.shutdown(); server.server_close(); thread.join()


def test_dataset_integrity_and_evidence():
    assert verify_freeze()['version'] == '1.0.0'
    cases = load_cases()
    assert Counter(c['split'] for c in cases) == {'development': 40, 'heldout': 20}
    assert len({c['id'] for c in cases}) == 60
    assert len({c['family'] for c in cases}) == 30
    assert len({c['category'] for c in cases}) == 8
    docs = {d['id'] for d in json.loads(data_path('documents.json').read_text())}
    assert all(set(c['evidence_ids']) <= docs for c in cases)


def test_split_leakage_rejected(tmp_path):
    cases = load_cases()[:2]; cases[1]['split'] = 'heldout'
    path = tmp_path / 'bad.jsonl'
    path.write_text('\n'.join(json.dumps(c) for c in cases))
    with pytest.raises(ValueError, match='crosses'):
        load_cases(path)


def test_callable_and_optional_retrieval():
    adapter = CallableAdapter(lambda req: {'answer': req.question, 'citations': []})
    result = adapter.ask(Request('Hello'))
    assert result.answer == 'Hello' and result.latency_ms >= 0
    assert result.retrieved_documents is None
    with pytest.raises(AdapterError):
        CallableAdapter(lambda _: {'answer': 1}).ask(Request('Hi'))


def test_http_contract(endpoint):
    url, seen = endpoint
    result = HttpAdapter(url).ask(Request('Next?', (Turn('First?', 'Answer'),)))
    assert result.citations == ['doc-a']
    assert seen[0][0]['history'][0]['question'] == 'First?'
    assert result.retrieved_documents is None


def test_portfolio_contract_and_origin(endpoint):
    url, seen = endpoint
    result = PortfolioAdapter(url + '/portfolio').ask(Request('C++?', (Turn('Work?', 'Answer', ('yojana',)),)))
    assert seen[0][0]['message'] == 'C++?'
    assert seen[0][0]['turns'][0]['projectIds'] == ['yojana']
    assert seen[0][1] == url
    assert result.citations == ['/resume.html']
    assert result.retrieved_documents is None  # Citation IDs are not retrieved text.


@pytest.mark.parametrize('path', ['/error', '/invalid'])
def test_transport_failures_are_not_answers(endpoint, path):
    with pytest.raises(AdapterError, match='HTTP 429' if path == '/error' else 'Invalid endpoint response'):
        HttpAdapter(endpoint[0] + path).ask(Request('Hi'))


def test_timeout_is_an_operational_error(monkeypatch):
    def timeout(*args, **kwargs):
        raise TimeoutError()
    monkeypatch.setattr('chatbot_eval.adapters.urlopen', timeout)
    with pytest.raises(AdapterError, match='timed out'):
        HttpAdapter('http://localhost/chat').ask(Request('Hello'))


def test_invalid_history_and_documents_rejected():
    with pytest.raises(ValueError):
        Turn('Question', 42)
    with pytest.raises(ValueError):
        Request('Question', ('not a turn',))
    with pytest.raises(AdapterError):
        CallableAdapter(lambda _: {'answer': 'Hello', 'retrieved_documents': [{'id': 4, 'text': 'x'}]}).ask(Request('Hi'))


def test_demo_uses_documents_and_exposes_evidence():
    response = respond(Request('Which database does Library Compass use?'))
    assert 'SQLite' in response.answer
    assert 'library' in response.citations
    assert response.retrieved_documents
    assert 'intermediate' in respond(Request('Does Mira know C++?')).answer


def test_demo_history_is_request_local():
    followup = Request('Which database does it use?', (Turn('Library Compass?', 'Library project'),))
    assert 'SQLite' in respond(followup).answer
    assert respond(Request('Is it done?')).mode == 'demo-unknown'


def test_capture_does_not_claim_quality_or_leak_error_text():
    def broken(_):
        raise RuntimeError('secret-credential')
    report = run(load_cases(split='development')[:1], CallableAdapter(broken), target='test')
    assert report['quality_scored'] is False and report['summary']['errors'] == 1
    assert 'secret-credential' not in json.dumps(report)


def test_budget_checked_before_calls():
    def forbidden(_):
        pytest.fail('Should not call')
    with pytest.raises(ValueError):
        run(load_cases(), CallableAdapter(forbidden), target='test', max_calls=1)


def test_cli_demo_capture(tmp_path):
    out = tmp_path / 'capture.json'
    assert main(['run', '--output', str(out)]) == 0
    report = json.loads(out.read_text())
    assert report['summary']['cases'] == 40
    assert not report['quality_scored']


@pytest.mark.parametrize('args', [
    ['run', '--split', 'heldout'],
    ['run', '--target', 'portfolio'],
    ['run', '--target', 'http', '--dataset', 'missing.jsonl'],
])
def test_cli_requires_explicit_target_data_network_and_heldout(args):
    with pytest.raises(SystemExit) as exc:
        main(args)
    assert exc.value.code == 2
