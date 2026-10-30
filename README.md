# Chatbot Eval Kit

Run a set of questions against a chatbot and inspect its answers, sources, response times and errors.

The current version collects results for review. It does not yet score answer quality. A small document-based demo lets you try it without an API key.

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
|-- examples/
|   |-- portfolio-cases.jsonl          # two portfolio-specific questions
|   `-- private_retrieval_adapter.py   # optional local portfolio connection
|-- src/
|   `-- chatbot_eval/
|       |-- __init__.py        # convenient Python imports
|       |-- models.py          # question, answer and document structures
|       |-- adapters.py        # connects Python functions and HTTP APIs
|       |-- dataset.py         # loads and validates cases
|       |-- runner.py          # runs cases and collects responses
|       |-- cli.py             # terminal commands
|       |-- demo.py            # offline example chatbot
|       `-- data/
|           |-- documents.json # fictional demo knowledge
|           |-- cases.jsonl    # 60 questions and expected behavior
|           `-- manifest.json  # dataset version and file hashes
`-- tests/
    `-- test_foundations.py    # toolkit tests
```

`pyproject.toml` lists dependencies, like `requirements.txt`, and also defines package installation, the `chatbot-eval` command and pytest settings. This project uses it as the single configuration file; a separate requirements file is not needed. There are no runtime dependencies; pytest is a development dependency.

Normal use does not require building a distribution. Installation handles package setup automatically. The runner records execution errors separately from answers: successful execution does not mean an answer is correct. Semantic scoring and runtime protections are planned additions.

## Demo results

[Read the Phase 1 baseline review](EVALUATION.md): 40 captured responses, manually reviewed as 32 pass, 3 partial and 5 fail. The CLI does not score answers automatically; the review explains the failures and limits.
