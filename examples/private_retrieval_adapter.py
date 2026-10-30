"""Optional LOCAL adapter. Imports your checkout; does not copy or publish it.

Set PORTFOLIO_REPO to your private portfolio checkout and put examples on PYTHONPATH.
Use --target callable --function private_retrieval_adapter:respond --dataset YOUR_CASES.
Only use public-safe evidence in outputs. No HTTP debugging route is created.
"""
import json
import os
import subprocess
from pathlib import Path
from chatbot_eval import Response, Document


def respond(request):
    root = Path(os.environ['PORTFOLIO_REPO']).resolve()
    script = '''
const fs = require('node:fs');
const path = require('node:path');
const root = process.argv[1];
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const { selectContext } = require(path.join(root, 'lib/retrieval.cjs'));
const result = selectContext(input.question, input.history.map(t => t.question), undefined, input.history);
process.stdout.write(JSON.stringify(result));
'''
    history = [{'question': t.question, 'answer': t.answer, 'projectIds': list(t.project_ids)} for t in request.history]
    result = subprocess.run(['node', '-e', script, str(root)],
                            input=json.dumps({'question': request.question, 'history': history}),
                            text=True, capture_output=True, check=True, timeout=20)
    selection = json.loads(result.stdout)
    docs = [Document(d['id'], d['text']) for d in selection['docs']]
    return Response(selection.get('answer') or '', [d.id for d in docs], docs,
                    mode='retrieval-only', metadata={'kind': selection.get('kind')})
