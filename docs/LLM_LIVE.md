# Live LLM verification

On **5 October 2026**, the final Groq `openai/gpt-oss-20b` smoke run passed
**14/14 checks**, receiving all **11 real provider responses**. This verifies the
provider connection and the exercised intent/explanation paths. It does not
establish full-stack search quality or general prompt-injection immunity.

A subsequent [full-stack rules/Groq evaluation](LLM_STACK_EVALUATION.md) now covers
120 synthetic queries, fresh-call latency, cached-intent throughput and real
end-to-end explanation samples. It found no significant overall relevance gain.
The smoke checks below remain separate security/integration evidence.

| Check | Final result |
|---|---|
| One intent query each in English, Tamil, Tanglish, Hindi and Hinglish | 5/5 used `llm+rules`, with expected category/material and preserved rule constraints |
| Validated intent cache hit | Passed without another provider call |
| Three instruction-like intent queries | Rule-derived hard constraints preserved |
| Normal explanation and two requests to invent claims | 3/3 returned ordered complete approved sentences; all used the live model |
| Corrupt cached JSON and provider connection failure | Both injected faults returned rules with warnings |

## What ran

`evaluation/validate_llm.py` sends requests to the real `/parse` and `/rank`
FastAPI routes using an in-process HTTP transport. Model calls go to Groq.
Redis is replaced with a memory fixture, and ranking receives one synthetic product.
The script explicitly enables optional explanations in its own process;
`LLM_EXPLANATIONS` remains `false` by default for normal application runs.

The gateway, real Redis, catalogue, retrieval, model encoders, UI and Docker deployment
were not exercised. Language checks use one example per language and inspect a small
set of fields; they are not a multilingual accuracy benchmark. Faults are injected,
not outages observed at Groq. Connection failures seen in development mean the
successful final run is not an uptime guarantee.

## Fixes found during verification

- Updated the retired Groq Llama default to `openai/gpt-oss-20b`.
- Groq GPT-OSS requests now use low reasoning effort and 1,024 completion tokens,
  including reasoning, instead of the previous 400-token allowance. This provides
  more room for the JSON response.
- Clarified the intent prompt: absent array fields must be `[]`, never `null`.
  A real response previously used null arrays and was correctly rejected. The
  strict validator and rule fallback remain in place.

Earlier checks encountered connection errors, HTTP 400 responses and rejected
null-array outputs. Those failures are preserved; the final report is not a claim
that every development request succeeded. The focused image-security, LLM-security
and ranking regression suite passed **44 tests**, including new Groq request-budget
and null-array rejection checks.

## Evidence and reproduction

- [Final machine-readable report](../evaluation/reports/llm_live.json): synthetic inputs,
  parsed intents, provider outputs, model, timing, base commit and source-file hashes.
  `source_commit` is the base commit; the run included working-tree fixes identified
  by the recorded hashes.
- [Development run history](../evaluation/reports/llm_live_history.json): initial failures
  and checks before the final run.

Configure the local `.env` with the provider, model and key, then run:

```bash
PYTHONPATH=libs:. python -m evaluation.validate_llm
python -m pytest tests/test_image_security.py tests/test_llm_security.py tests/test_ranking.py -q
```

On PowerShell, set `$env:PYTHONPATH="libs;."` before the Python command.
The smoke check makes real API calls and overwrites the final report. Keep `.env`
out of Git. Reports contain only synthetic test data and safe configuration metadata;
the script checks for the configured key before writing them.

Broader adversarial testing and provider-backed relevance/load evaluation remain
future work. Historical relevance results still describe the rule-based baseline.
