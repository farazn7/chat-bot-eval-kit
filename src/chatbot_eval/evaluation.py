"""Offline evidence metrics, not natural-language correctness judgments."""
import hashlib
import json
from statistics import mean


def _ids(value, name):
    if not isinstance(value, list) or not all(isinstance(x, str) and x for x in value):
        raise ValueError(f"{name} must be a list of non-empty strings")
    return list(dict.fromkeys(value))


def evaluate(capture, documents):
    """Use caller-supplied source IDs; missing retrieval stays unmeasured."""
    if not isinstance(documents, list) or not documents:
        raise ValueError("Provide a non-empty source document list")
    known = _ids([d.get('id') if isinstance(d, dict) else None for d in documents], 'document IDs')
    if len(known) != len(documents):
        raise ValueError("Duplicate source document IDs")
    known = set(known)
    records = capture.get('records')
    if not isinstance(records, list) or not records:
        raise ValueError("Capture must contain records")
    seen, rows = set(), []
    for record in records:
        case_id = record.get('id')
        if not isinstance(case_id, str) or not case_id or case_id in seen:
            raise ValueError("Case IDs must be non-empty and unique")
        seen.add(case_id)
        expected = set(_ids(record.get('evidence_ids'), 'evidence_ids'))
        if not expected <= known:
            raise ValueError(f"{case_id}: expected evidence is absent from supplied documents")
        row = {k: record.get(k) for k in ('id', 'question', 'history', 'expected_behavior', 'evidence_ids', 'split', 'category')}
        row.update(status=record.get('status'), empty_answer=None,
                   invalid_citation_ids=None, citation_evidence_recall=None,
                   retrieval_precision=None, retrieval_recall=None, retrieval_mrr=None)
        if row['status'] == 'captured':
            response = record.get('response', {})
            answer = response.get('answer')
            if not isinstance(answer, str):
                raise ValueError(f"{case_id}: answer must be text")
            citations = set(_ids(response.get('citations'), 'citations'))
            row['empty_answer'] = not answer.strip()
            row['invalid_citation_ids'] = sorted(citations - known)
            if expected:
                row['citation_evidence_recall'] = len(expected & citations) / len(expected)
            retrieved = response.get('retrieved_documents')
            if retrieved is not None:
                if not isinstance(retrieved, list):
                    raise ValueError('retrieved_documents must be a list or null')
                ranked = _ids([d.get('id') if isinstance(d, dict) else None for d in retrieved], 'retrieved IDs')
                if expected:
                    hits = expected & set(ranked)
                    row['retrieval_precision'] = len(hits) / len(ranked) if ranked else 0.0
                    row['retrieval_recall'] = len(hits) / len(expected)
                    row['retrieval_mrr'] = next((1 / i for i, doc in enumerate(ranked, 1) if doc in expected), 0.0)
        elif row['status'] != 'error':
            raise ValueError(f"{case_id}: unknown capture status")
        rows.append(row)
    metrics = {}
    for key in ('citation_evidence_recall', 'retrieval_precision', 'retrieval_recall', 'retrieval_mrr'):
        values = [r[key] for r in rows if r[key] is not None]
        metrics[key] = {'mean': mean(values) if values else None, 'measured_cases': len(values)}
    return {'schema_version': 1, 'kind': 'evidence-metrics', 'answer_quality_scored': False,
            'documents_sha256': hashlib.sha256(json.dumps(documents, sort_keys=True).encode()).hexdigest(),
            'target': capture.get('target'), 'dataset_version': capture.get('dataset_version'),
            'summary': {'cases': len(rows), 'errors': sum(r['status'] == 'error' for r in rows),
                        'empty_answers': sum(r['empty_answer'] is True for r in rows),
                        'cases_with_invalid_citations': sum(bool(r['invalid_citation_ids']) for r in rows)},
            'metrics': metrics, 'records': rows}


def compare(before, after):
    """Compare paired cases only; never silently compare different experiments."""
    for report in (before, after):
        if report.get('kind') != 'evidence-metrics':
            raise ValueError('Comparison requires evaluated reports')
    if before.get('dataset_version') != after.get('dataset_version'):
        raise ValueError('Dataset versions differ')
    if before.get('documents_sha256') != after.get('documents_sha256'):
        raise ValueError('Source documents differ')
    def index(report):
        rows = report.get('records', [])
        result = {r['id']: r for r in rows}
        if not result or len(result) != len(rows):
            raise ValueError('Comparison requires unique, non-empty case sets')
        return result
    left, right = index(before), index(after)
    if left.keys() != right.keys():
        raise ValueError('Case sets differ; use the same cases for comparison')
    changes = []
    for case_id, old in left.items():
        new = right[case_id]
        for field in ('question', 'history', 'expected_behavior', 'evidence_ids', 'split', 'category'):
            if old[field] != new[field]:
                raise ValueError(f'{case_id}: {field} changed')
        deltas = {}
        for field in ('citation_evidence_recall', 'retrieval_precision', 'retrieval_recall', 'retrieval_mrr'):
            a, b = old[field], new[field]
            deltas[field] = b - a if a is not None and b is not None else None
        changes.append({'id': case_id, 'before_status': old['status'], 'after_status': new['status'],
                        'deltas': deltas, 'before_empty': old['empty_answer'], 'after_empty': new['empty_answer'],
                        'before_invalid_citations': old['invalid_citation_ids'],
                        'after_invalid_citations': new['invalid_citation_ids']})
    summary = {}
    for field in changes[0]['deltas']:
        values = [r['deltas'][field] for r in changes if r['deltas'][field] is not None]
        summary[field] = {'paired_cases': len(values), 'mean_delta': mean(values) if values else None,
                          'improved': sum(v > 0 for v in values), 'regressed': sum(v < 0 for v in values)}
    return {'kind': 'paired-evidence-comparison', 'answer_quality_scored': False,
            'metrics': summary, 'records': changes}
