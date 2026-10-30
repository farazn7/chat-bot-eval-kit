"""Optional Groq judge; standard library only, credentials from the environment."""
import json
import os
import time
from pathlib import Path
from urllib.request import Request, urlopen


class GroqJudge:
    def __init__(self, *, model='openai/gpt-oss-20b', min_interval=12):
        self.key = os.environ.get('GROQ_API_KEY')
        if not self.key and Path('.env').is_file():
            for line in Path('.env').read_text(encoding='utf-8-sig').splitlines():
                name, separator, value = line.strip().partition('=')
                if separator and name == 'GROQ_API_KEY':
                    self.key = value.strip().strip('\"').strip("'")
        if not self.key:
            raise ValueError('Set GROQ_API_KEY in your process environment or local .env')
        self.model = model
        self.min_interval = min_interval
        self.last_call = None
        self.stopped = False
        self.calls = 0
        self.usage = {'prompt_tokens': 0, 'completion_tokens': 0, 'total_tokens': 0}

    def __call__(self, payload):
        if self.stopped:
            raise RuntimeError('Provider run stopped after an earlier failure')
        if self.last_call is not None:
            time.sleep(max(0, self.min_interval - (time.monotonic() - self.last_call)))
        schema = {'type': 'object', 'additionalProperties': False,
                  'properties': {'label': {'type': 'string', 'enum': ['pass', 'partial', 'fail']},
                                 'reason': {'type': 'string'},
                                 'evidence_ids': {'type': 'array', 'items': {'type': 'string'}}},
                  'required': ['label', 'reason', 'evidence_ids']}
        body = {'model': self.model, 'temperature': 0, 'reasoning_effort': 'low',
                'max_completion_tokens': 1200,
                'messages': [{'role': 'system', 'content': json.dumps(payload['rubric'])},
                             {'role': 'user', 'content': json.dumps({k: v for k, v in payload.items() if k != 'rubric'})}],
                'response_format': {'type': 'json_schema', 'json_schema': {
                    'name': 'answer_grade', 'strict': True, 'schema': schema}}}
        request = Request('https://api.groq.com/openai/v1/chat/completions',
                          data=json.dumps(body).encode(), method='POST',
                          headers={'Authorization': 'Bearer ' + self.key, 'Content-Type': 'application/json',
                                   'User-Agent': 'chatbot-eval-kit/0.1'})
        self.last_call = time.monotonic()
        self.calls += 1
        try:
            with urlopen(request, timeout=45) as response:
                value = json.loads(response.read())
            for key in self.usage:
                self.usage[key] += value.get('usage', {}).get(key, 0)
            choice = value['choices'][0]
            if choice.get('finish_reason') != 'stop':
                raise ValueError('Incomplete judge response')
            return json.loads(choice['message']['content'])
        except Exception:
            self.stopped = True  # No retries or repeated calls after authentication/rate-limit failure.
            raise


_judge = None


def grade(payload):
    global _judge
    if _judge is None:
        _judge = GroqJudge()
    return _judge(payload)
