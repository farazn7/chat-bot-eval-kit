# Chatbot Eval Kit

Run a set of questions against a chatbot and inspect its answers, sources, response times and errors.

Capture responses, measure evidence coverage, and optionally grade answers through your own model judge. A small document-based demo lets you try the capture and evidence checks without an API key.

## Get started

Requires Python 3.11 or newer. On Windows:

```powershell
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev]"
.venv/Scripts/chatbot-eval run
.venv/Scripts/python -m pytest
```

On macOS/Linux, replace `.venv/Scripts/` with `.venv/bin/`.

The demo run saves 40 question-and-answer records to `reports/capture.json`. Open that file to compare responses with their expected behavior. The demo uses keyword matching over fictional documents, not a language model, so expect imperfect answers.

## Connect your chatbot

Use a Python function through `CallableAdapter`, or an HTTP endpoint through `HttpAdapter`:

```python
from chatbot_eval import HttpAdapter, Request

bot = HttpAdapter("http://127.0.0.1:9000/chat")
result = bot.ask(Request("What does this project do?"))
print(result.answer)
```

The HTTP adapter sends `question` and `history`. It expects `answer` and a list of `citations`; `retrieved_documents` is optional. Each retrieved document has an `id` and `text`. Adapters let different chatbots use the same runner without changing their own APIs. See `examples/` for the portfolio integration.

To run your own dataset:

```powershell
chatbot-eval run --target http --endpoint http://127.0.0.1:9000/chat --dataset my-cases.jsonl --allow-network --max-calls 40
```

Use questions and evidence that belong to your target. Live endpoints may incur provider costs. Reports stay local and are ignored by Git; review their contents before sharing.

## Test cases

Each JSONL line contains `id`, `family`, `split`, `category`, `question`, `history`, `expected_behavior` and `evidence_ids`. History contains prior question/answer pairs; evidence IDs refer to supporting documents. Expectations describe what a good answer should do rather than requiring identical wording.

The bundled dataset has 60 cases: 40 for development and 20 reserved for later evaluation. Related paraphrases stay in the same split. Cases cover known and unknown facts, partial answers, follow-ups, topic changes and adversarial questions.

`chatbot-eval validate` checks the dataset and its saved hashes. Reserved cases require `--split heldout --include-heldout`; avoid using them to tune the demo. Missing retrieval data remains unavailable rather than being inferred from citations.

## Project layout

```text
chatbot-eval-kit/
|-- .gitattributes              # consistent line endings for dataset hashes
|-- .gitignore                 # keeps local/generated files out of Git
|-- pyproject.toml             # dependencies, package and command configuration
|-- README.md
|-- EVALUATION.md              # saved demo baseline review and limitations
|-- examples/
|   |-- groq_judge.py                  # optional live judge; key from environment or ignored .env
|   |-- portfolio-cases.jsonl          # two portfolio-specific questions
|   `-- private_retrieval_adapter.py   # optional local portfolio connection
|-- src/
|   `-- chatbot_eval/
|       |-- __init__.py        # convenient Python imports
|       |-- models.py          # question, answer and document structures
|       |-- adapters.py        # connects Python functions and HTTP APIs
|       |-- dataset.py         # loads and validates cases
|       |-- runner.py          # runs cases and collects responses
|       |-- evaluation.py      # offline evidence metrics and paired comparison
|       |-- judging.py         # rubric grading and reference-label calibration
|       |-- experiment.py      # frozen-design, real multi-turn capture and session isolation
|       |-- cli.py             # terminal commands
|       |-- demo.py            # offline example chatbot
|       `-- data/
|           |-- documents.json # fictional demo knowledge
|           |-- cases.jsonl    # 60 questions and expected behavior
|           `-- manifest.json  # dataset version and file hashes
`-- tests/
    |-- test_foundations.py    # capture and adapter tests
    |-- test_evaluation.py     # evidence metrics and comparison tests
    |-- test_judging.py        # judge contracts and provider tests
    `-- test_experiment.py     # conversations, budgets, isolation and interruption tests
```

`pyproject.toml` lists dependencies, like `requirements.txt`, and also defines package installation, the `chatbot-eval` command and pytest settings. This project uses it as the single configuration file; a separate requirements file is not needed. There are no runtime dependencies; pytest is a development dependency.

Normal use does not require building a distribution. Installation handles package setup automatically. Successful execution does not mean an answer is correct. Runtime protections are not implemented.

## Demo results

[Read the Phase 1 baseline review](EVALUATION.md): 40 captured responses, assistant-reviewed as 32 pass, 3 partial and 5 fail. That baseline was not graded by an automated judge; the review explains its failures and limits.

## Offline evidence checks

```powershell
chatbot-eval evaluate reports/demo.json --documents src/chatbot_eval/data/documents.json --output reports/demo-evaluation.json
chatbot-eval compare reports/before-evaluation.json reports/after-evaluation.json --output reports/comparison.json
```

Supply your target's source documents as a JSON list with unique `id` fields. Evaluation measures citation evidence coverage, unknown citation IDs, retrieval precision/recall/reciprocal rank, empty answers and execution errors. These do not establish factual correctness or citation entailment. Cases without expected evidence are excluded from evidence averages; missing retrieval stays unmeasured, while an explicitly empty retrieval scores zero when evidence was expected. Each average includes its measured-case count.

Comparison requires matching cases, expectations, dataset version and source documents. It reports paired improvements and regressions without treating missing measurements as zero. This command compares evidence metrics, not semantic grades.

## Grade answers and check the judge

Use a trusted Python function `grade(payload)` in your own module. The payload contains `rubric`, `documents`, `case` (question/history/expectation) and `candidate` (answer/citations). Send the rubric as instructions and the remaining fields as untrusted data to your chosen model. Return a Python dictionary with exactly these keys:

```python
{"label": "partial", "reason": "Answers the known part but omits the unknown part.",
 "evidence_ids": ["your-source-id"]}
```

Labels are `pass`, `partial` or `fail`. The toolkit validates the response, retains reasons, records errors separately and never automatically retries. The function owns provider credentials, model parameters, timeouts and any provider-specific parsing; keep secrets in environment variables. The call budget limits callable invocations, not any internal retries your function makes.

```powershell
chatbot-eval judge reports/demo.json --documents src/chatbot_eval/data/documents.json --function my_judge:grade --judge-id provider-model-config-v1 --allow-judge-calls --max-calls 40 --output reports/demo-judgments.json
chatbot-eval review-template reports/demo.json --documents src/chatbot_eval/data/documents.json --output reports/demo-reference.json
```

`my_judge` is your importable module, not a bundled provider. Judge calls can send the supplied answers and documents to that provider and incur its charges. The demo and offline commands require none of this configuration.

For the bundled Groq example, set `GROQ_API_KEY` in your process environment or in a Git-ignored `.env` at the repository root. Never commit that file. From the repository root:

```powershell
$env:PYTHONPATH = 'examples'
chatbot-eval judge reports/demo.json --documents src/chatbot_eval/data/documents.json --function groq_judge:grade --judge-id groq-gpt-oss-20b-temp0-low-1200-rubric1 --allow-judge-calls --max-calls 40 --output reports/demo-groq-judgments.json
```

The example uses Groq's `openai/gpt-oss-20b` with strict JSON output, temperature 0, low reasoning effort and a 1,200-token response cap. It spaces requests 12 seconds apart, uses a 45-second timeout and stops further provider calls after an error. This pacing is not a guarantee against your account's rate limits. See the [Groq structured-output documentation](https://console.groq.com/docs/structured-outputs) for the API contract.

Have a reviewer fill the template's `reviewer`, `provenance`, and each case's `label` and `reason` without seeing judge grades. The template includes the questions, answers, evidence and rubric. Then run:

```powershell
chatbot-eval calibrate reports/demo-judgments.json reports/demo-reference.json --output reports/demo-calibration.json
```

Calibration reports agreement, a confusion matrix, individual disagreements and false passes (judge says pass where reference says partial/fail). It binds labels to the exact capture, source documents and rubric, rejects incomplete labels and reports judge failures separately. Agreement uses successfully judged pairs; inspect its denominator and error count. Reference provenance is recorded, but reviewer independence cannot be verified automatically. Do not call assistant-generated labels independent human ground truth.

The toolkit has 72 passing tests and one completed 40-case demo judge run. Groq agreed with the prior assistant review on 37 cases; this is not independent human calibration. See [the results and disagreements](EVALUATION.md). Keep development and held-out reviews separate, record judge configuration changes, and inspect disagreements before trusting model grades.

## Multi-turn experiments

The `experiment` command runs fixed conversations against variants defined in a local frozen design. Every follow-up receives actual previous replies. Each scenario, variant and repeat starts a fresh session; forged-history fixtures are explicitly labeled. Evaluator expectations and attack objectives are never sent to the answer model.

A design folder contains `specification.json`, `evidence.json`, `scenarios.jsonl` and `design-manifest.json`. The manifest records the version and SHA-256 hashes of the other three files. The specification defines prompts, generation settings, repeats and limits. Scenarios contain an ID, family, split, kind, evidence IDs and user turns with expected behavior; optional fields describe injected history/evidence and synthetic-canary fixtures. The personal portfolio design is local and ignored, not part of this package.

First plan a run without loading credentials or importing a provider:

```powershell
chatbot-eval experiment path/to/design --variants minimal restrictive --max-calls 200
```

To execute an explicitly budgeted run using the bundled Groq example, from the repository root:

```powershell
$env:PYTHONPATH = 'examples'
chatbot-eval experiment path/to/design --variants minimal restrictive --max-calls 200 --execute --function groq_judge:answer_factory --provider-id groq-gpt-oss-20b-design-settings --output reports/new-experiment-run.json
```

The factory returns a fresh stateless callable accepting `system`, `question`, `history`, `documents`, `generation` and `answer_schema`, and returning exactly `answer` and `citations`. Groq uses the frozen model settings; only HTTP pacing and credentials are shared across sessions. Custom providers must honor supplied settings and implement their own timeouts with no hidden retries. The call limit counts callable invocations, not arbitrary behavior inside custom code.

Execution requires a new output file and checkpoints every turn. Provider failure stops further calls; incomplete sessions remain visible. If interrupted, an `in_flight` call may have incurred usage even though its answer was not captured. There is no automatic resume or retry: preserve that report and account for it before starting a separately named run. Histories exceeding limits stop rather than silently truncate. Held-out runs require `--split heldout --include-heldout`.

Unknown citations, injected-source citations and empty answers are recorded, not repaired or counted as quality passes. Synthetic-canary checks detect literal, base64 and hex forms, including concatenated replies; absence of a match does not prove non-disclosure. Semantic correctness, helpfulness and attack success still require separate review. This runner does not yet implement the planned balanced code guards, renderer protections, load testing or adaptive red teaming. Its experiment reports are not inputs to the single-turn `evaluate`/`judge` commands without an explicit conversion and matching evaluation protocol.
