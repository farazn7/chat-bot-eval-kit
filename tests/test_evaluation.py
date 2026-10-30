import copy
import json
import pytest
from chatbot_eval.evaluation import evaluate, compare
from chatbot_eval.cli import main


def capture(retrieved=None, answer='Known fact', citations=None):
    return {'dataset_version': 'test', 'target': 'fixture', 'records': [
        {'id': 'one', 'question': 'Question?', 'history': [], 'expected_behavior': 'Answer fact',
         'evidence_ids': ['a'], 'split': 'development', 'category': 'known', 'status': 'captured',
         'response': {'answer': answer, 'citations': citations or [], 'retrieved_documents': retrieved}}]}


DOCS = [{'id': 'a', 'text': 'Known fact'}, {'id': 'b', 'text': 'Other fact'}]


def test_missing_empty_and_irrelevant_retrieval_differ():
    assert evaluate(capture(), DOCS)['metrics']['retrieval_recall'] == {'mean': None, 'measured_cases': 0}
    empty = evaluate(capture([]), DOCS)
    assert empty['metrics']['retrieval_recall']['mean'] == 0
    ranked = evaluate(capture([DOCS[1], DOCS[0], DOCS[0]]), DOCS)
    assert ranked['metrics']['retrieval_recall']['mean'] == 1
    assert ranked['metrics']['retrieval_precision']['mean'] == 0.5
    assert ranked['metrics']['retrieval_mrr']['mean'] == 0.5


def test_citations_do_not_establish_truth_or_retrieval():
    report = evaluate(capture(answer='A completely false claim', citations=['a', 'bogus']), DOCS)
    assert report['metrics']['citation_evidence_recall']['mean'] == 1
    assert report['metrics']['retrieval_recall']['mean'] is None
    assert report['summary']['cases_with_invalid_citations'] == 1
    assert report['answer_quality_scored'] is False


def test_unknown_questions_and_transport_errors_are_not_quality_scores():
    source = capture([], answer=' ')
    source['records'][0]['evidence_ids'] = []
    report = evaluate(source, DOCS)
    assert report['summary']['empty_answers'] == 1
    assert report['metrics']['retrieval_recall']['measured_cases'] == 0
    source['records'][0]['status'] = 'error'
    del source['records'][0]['response']
    report = evaluate(source, DOCS)
    assert report['summary']['errors'] == 1
    assert report['summary']['empty_answers'] == 0


def test_wrong_corpus_and_duplicate_case_ids_rejected():
    with pytest.raises(ValueError, match='absent'):
        evaluate(capture(), [DOCS[1]])
    source = capture()
    source['records'] *= 2
    with pytest.raises(ValueError, match='unique'):
        evaluate(source, DOCS)


def test_compare_detects_regression_and_missing_measurements():
    good = evaluate(capture([DOCS[0]], citations=['a']), DOCS)
    bad = evaluate(capture([]), DOCS)
    result = compare(good, bad)
    assert result['metrics']['retrieval_recall']['regressed'] == 1
    assert result['metrics']['retrieval_recall']['mean_delta'] == -1
    missing = evaluate(capture(), DOCS)
    assert compare(good, missing)['metrics']['retrieval_recall']['paired_cases'] == 0
    assert compare(good, good)['metrics']['retrieval_recall']['mean_delta'] == 0


@pytest.mark.parametrize('field', ['question', 'history', 'evidence_ids', 'expected_behavior', 'split'])
def test_compare_rejects_changed_cases(field):
    baseline = evaluate(capture(), DOCS)
    changed = copy.deepcopy(baseline)
    changed['records'][0][field] = 'changed'
    with pytest.raises(ValueError, match='changed'):
        compare(baseline, changed)


def test_compare_rejects_different_corpora_and_case_sets():
    baseline = evaluate(capture(), DOCS)
    other = evaluate(capture(), [dict(DOCS[0], text='Changed fact'), DOCS[1]])
    with pytest.raises(ValueError, match='documents'):
        compare(baseline, other)
    other = copy.deepcopy(baseline)
    other['records'][0]['id'] = 'other'
    with pytest.raises(ValueError, match='Case sets'):
        compare(baseline, other)


def test_cli_offline_evaluation_and_comparison(tmp_path):
    source, docs, scored, comparison = [tmp_path / name for name in ('raw.json', 'docs.json', 'eval.json', 'diff.json')]
    source.write_text(json.dumps(capture([DOCS[0]])))
    docs.write_text(json.dumps(DOCS))
    assert main(['evaluate', str(source), '--documents', str(docs), '--output', str(scored)]) == 0
    assert main(['compare', str(scored), str(scored), '--output', str(comparison)]) == 0
    assert json.loads(comparison.read_text())['metrics']['retrieval_recall']['mean_delta'] == 0
    with pytest.raises(SystemExit):
        main(['evaluate', str(source), '--documents', str(docs), '--output', str(source)])
