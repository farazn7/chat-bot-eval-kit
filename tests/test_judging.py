import copy
import json
import sys
import types
import importlib.util
from pathlib import Path
import pytest
from chatbot_eval.judging import judge, review_template, calibrate
from chatbot_eval.cli import main


DOCS = [{'id': 'skills', 'text': 'Python is documented; Rust is not documented.'}]


def capture():
    return {'records': [{'id': 'mixed', 'status': 'captured', 'question': 'Python and Rust?',
                         'history': [], 'expected_behavior': 'Answer known part, qualify unknown part',
                         'evidence_ids': ['skills'], 'response': {'answer': 'Unknown.', 'citations': []}}]}


def result(label='fail'):
    return {'label': label, 'reason': 'Known Python part omitted.', 'evidence_ids': ['skills']}


def reference(source):
    ref = review_template(source, DOCS)
    ref.update(reviewer='Test fixture author', provenance='Synthetic test labels, not independent calibration')
    for row in ref['records']:
        row.update(label='fail', reason='Known part omitted')
    return ref


def test_judge_receives_context_evidence_rubric_not_reference_labels():
    seen = []
    def function(payload):
        seen.append(payload)
        return result()
    source = capture()
    report = judge(source, DOCS, function, judge_id='fixture-v1')
    assert set(seen[0]) == {'rubric', 'documents', 'case', 'candidate'}
    assert seen[0]['case']['expected_behavior'] == source['records'][0]['expected_behavior']
    assert seen[0]['documents'] == DOCS
    assert report['label_counts'] == {'fail': 1}
    assert report['calibrated'] is False
    assert review_template(source, DOCS)['records'][0]['label'] is None


@pytest.mark.parametrize('bad', [None, {'label': 'pass'}, result('excellent'),
                               dict(result(), evidence_ids=['invented']), dict(result(), reason='')])
def test_invalid_judge_outputs_are_errors_not_passes(bad):
    report = judge(capture(), DOCS, lambda _: bad, judge_id='broken')
    assert report['summary'] == {'judge_error': 1}
    assert not report['label_counts']


def test_budget_preflight_and_error_privacy():
    def forbidden(_):
        pytest.fail('Should not call')
    with pytest.raises(ValueError, match='budget'):
        judge(capture(), DOCS, forbidden, judge_id='fixture', max_calls=0)
    def broken(_):
        raise RuntimeError('private-token')
    report = judge(capture(), DOCS, broken, judge_id='fixture')
    assert 'private-token' not in json.dumps(report)


def test_invalid_later_case_prevents_all_judge_calls():
    source = capture()
    later = copy.deepcopy(source['records'][0])
    later.update(id='later', expected_behavior='')
    source['records'].append(later)
    with pytest.raises(ValueError, match='expected behavior'):
        judge(source, DOCS, lambda _: pytest.fail('Should not call'), judge_id='fixture')


def test_capture_errors_skip_judge_and_are_retained():
    source = capture()
    source['records'][0]['status'] = 'error'
    report = judge(source, DOCS, lambda _: pytest.fail('Should not call'), judge_id='fixture')
    assert report['summary'] == {'capture_error': 1}


def test_calibration_reports_false_passes_and_disagreements():
    source = capture()
    report = judge(source, DOCS, lambda _: result('pass'), judge_id='fixture')
    calibration = calibrate(report, reference(source))
    assert calibration['agreement'] == 0
    assert calibration['false_pass_rate'] == 1
    assert calibration['confusion_matrix_reference_rows']['fail']['pass'] == 1
    assert calibration['disagreements'][0]['id'] == 'mixed'


def test_judge_errors_are_visible_not_disagreements_or_zero_scores():
    source = capture()
    report = judge(source, DOCS, lambda _: None, judge_id='fixture')
    calibration = calibrate(report, reference(source))
    assert calibration['paired_cases'] == 0
    assert calibration['agreement'] is None
    assert calibration['judge_error_ids'] == ['mixed']


@pytest.mark.parametrize('change', ['capture', 'documents', 'rubric', 'duplicate', 'missing', 'blank', 'provenance'])
def test_calibration_rejects_mismatched_or_unreviewed_labels(change):
    source = capture()
    report = judge(source, DOCS, lambda _: result(), judge_id='fixture')
    ref = reference(source)
    if change in ('capture', 'documents'):
        ref[change + '_sha256'] = 'different'
    elif change == 'rubric':
        ref['rubric'] = {'version': 'different'}
    elif change == 'duplicate':
        ref['records'] *= 2
    elif change == 'missing':
        ref['records'] = []
    elif change == 'blank':
        ref['records'][0]['label'] = None
    else:
        ref['provenance'] = ''
    with pytest.raises(ValueError):
        calibrate(report, ref)


def test_judge_cannot_mutate_next_case_rubric_or_evidence():
    source = capture()
    second = copy.deepcopy(source['records'][0]); second['id'] = 'second'
    source['records'].append(second)
    seen = []
    def function(payload):
        seen.append(len(payload['documents']))
        payload['documents'].clear()
        return result()
    judge(source, DOCS, function, judge_id='fixture')
    assert seen == [1, 1]


def test_cli_judge_gate_template_and_calibration(tmp_path, monkeypatch):
    source, docs, output, labels, cal = [tmp_path / n for n in ('raw.json', 'docs.json', 'judge.json', 'labels.json', 'cal.json')]
    source.write_text(json.dumps(capture())); docs.write_text(json.dumps(DOCS))
    module = types.ModuleType('fixture_judge')
    module.grade = lambda _: result()
    monkeypatch.setitem(sys.modules, 'fixture_judge', module)
    args = ['judge', str(source), '--documents', str(docs), '--function', 'fixture_judge:grade',
            '--judge-id', 'test-only', '--output', str(output)]
    with pytest.raises(SystemExit):
        main(args)
    assert not output.exists()
    assert main(args + ['--allow-judge-calls']) == 0
    assert main(['review-template', str(source), '--documents', str(docs), '--output', str(labels)]) == 0
    labels.write_text(json.dumps(reference(capture())))
    assert main(['calibrate', str(output), str(labels), '--output', str(cal)]) == 0
    assert json.loads(cal.read_text())['agreement'] == 1


def test_groq_example_contract_and_fail_fast(monkeypatch):
    spec = importlib.util.spec_from_file_location('groq_example', Path(__file__).parents[1] / 'examples/groq_judge.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setenv('GROQ_API_KEY', 'test-only-placeholder')
    seen = []
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self):
            return json.dumps({'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps(result())}}],
                               'usage': {'total_tokens': 12}}).encode()
    def send(request, timeout):
        seen.append((request, timeout))
        return Response()
    monkeypatch.setattr(module, 'urlopen', send)
    provider = module.GroqJudge(min_interval=0)
    assert provider({'rubric': {'instruction': 'Grade'}, 'case': 'data'}) == result()
    body = json.loads(seen[0][0].data)
    assert seen[0][0].full_url == 'https://api.groq.com/openai/v1/chat/completions'
    assert body['response_format']['json_schema']['strict'] is True
    assert body['messages'][0]['role'] == 'system'
    assert provider.usage['total_tokens'] == 12
    def broken(*args, **kwargs):
        raise TimeoutError()
    monkeypatch.setattr(module, 'urlopen', broken)
    with pytest.raises(TimeoutError): provider({'rubric': {}})
    with pytest.raises(RuntimeError): provider({'rubric': {}})
    assert provider.calls == 2


def test_groq_env_file_and_environment_precedence(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location('groq_example', Path(__file__).parents[1] / 'examples/groq_judge.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv('GROQ_API_KEY', raising=False)
    (tmp_path / '.env').write_text('\ufeffGROQ_API_KEY="fixture-only"\n', encoding='utf-8')
    assert module.GroqJudge().key == 'fixture-only'
    monkeypatch.setenv('GROQ_API_KEY', 'process-fixture')
    assert module.GroqJudge().key == 'process-fixture'
