# Implementation Status

Last updated: 20 November 2026. Deadline: 20 November 2026.

## Summary

| Phase | Status | Verified by |
|---|---|---|
| 1. Workspace and scaffolding | Done | App starts, `/api/health` returns `ok` |
| 2. Data collection | Done for DarGlobal; **partial for Wasalt** | Scrape logs, raw JSONL row counts |
| 3. Data engineering | Done | 13 ingestion tests, manifest |
| 4. Knowledge base | Done | 325 chunks indexed; second run embeds 0 |
| 5. Retrieval | Done | 8 retrieval tests, evaluation (hit rate 100%) |
| 6. LLM integration | Done | 8 client tests against a mock provider; 30 live answers from OpenRouter free models |
| 7. Backend | Done | 13 API tests, manual curl checks |
| 8. Frontend | Done | Production build, headless-browser screenshots at desktop and phone size |
| 9. Reliability | Done | Guardrail, rate-limit, cache and outage tests |
| 10. Evaluation | Done | `backend/eval/REPORT.md` |
| 11. Docker | Done | Image built, container healthy under a 512 MB limit |
| 12. Deployment | **Not done: needs the owner's GitHub and Render accounts** | n/a |
| 13. Final delivery | README, status file, interview notes and email draft done; live URL pending | n/a |

## Waiting on the project owner

1. **OpenRouter API key.** Done: the key is in the git-ignored `.env`. It must also be entered in Render.
2. **GitHub repository.** Create an empty repository and push (commands in the README). Git for Windows is
   installed at `C:\Program Files\Git` but is not on the PowerShell PATH; Git Bash works.
3. **Render account.** New, Blueprint, pick the repository, enter the API key. Then the public URL must be
   opened and tested before it is called deployed.
4. **Decision on Wasalt coverage** (see limitation 1 below).

## What was verified, with results

| Check | Command | Result |
|---|---|---|
| Unit and API tests | `pytest` | 60 passed |
| DarGlobal scrape | `python -m app.scrapers.darglobal` | 38 projects, 14 press releases, 9 pages; 1 press page failed to load; 0 URLs disallowed by robots.txt |
| Wasalt live scrape | `python -m app.scrapers.wasalt` | Stopped at the first listing with HTTP 403 (Cloudflare challenge). No workaround attempted |
| Wasalt offline parse | `python -m app.scrapers.wasalt --from-html data/raw/wasalt_html` | 21 listings saved, 0 contact fields in the output |
| Ingestion | `python -m app.ingestion.pipeline --rebuild` | 88 records, 325 chunks |
| Incremental ingestion | run the pipeline again | embedded 0, unchanged 325 |
| Stale deletion | changed the chunk size and re-ran | 32 obsolete chunks deleted, 76 re-embedded |
| Retrieval evaluation | `python -m eval.run_eval` | Hybrid: hit rate 100%, recall 97.4%, MRR 0.926 on 26 questions |
| Relevance gate | same | 5 of 5 out-of-scope refused; 26 of 26 answerable passed |
| Injection screen | same | 4 of 4 attacks blocked; 0 of 36 normal questions blocked |
| Retrieval latency | same | p50 about 8 ms, p95 about 10 ms on the development machine |
| Generation evaluation | `python -m eval.run_eval --generation --pause 4` | Outcome accuracy 97.5%, fact coverage 100%, citation correctness 100%, numeric faithfulness 91.4%, hallucination rate 0%, p50 2.2 s, p95 21.4 s. 1 of 40 fell back to extractive mode; 4 answers hit the 700-token cap |
| Token-cap fix | raised the cap to 1500, rebuilt the container, re-asked a truncated question | Complete answer, 6 sources, 5.9 s |
| Live API without a key | curl against `uvicorn` | Degraded answer with sources; refusal for off-topic; block for injection |
| UI | headless Chromium | Empty state, answer with source cards, refusal state, history restored after reload, no console errors, no horizontal overflow at 390 px |
| Docker image | `docker build` | Builds; 759 MB |
| Container | `docker compose up` with a 512 MB limit | Health `ok`, 325 chunks, about 288 MB used, runs as non-root user |

## Known limitations

1. **Wasalt: 21 listings, all apartments for sale in Al-Mahdiyah, Riyadh.** Wasalt's `robots.txt` and
   `llms.txt` permit collecting public listing content, but its Cloudflare layer challenged the scraper's
   HTTP client. The scraper stops on a block by design. The indexed listings come from one page fetched
   during site inspection (the listing plus the 20 similar listings embedded in it). Compliant ways to
   widen coverage: save listing pages from a normal browser session and run the `--from-html` parser, or
   ask Wasalt for access.
2. **DarGlobal press releases: 14 of 72** (first page of the press list only).
3. **Free models are unreliable.** In the live run `google/gemma-4-31b-it:free` returned HTTP 429 on every
   attempt, so `nvidia/nemotron-3.5-super-vl:free` is now first in the chain (it served 27 of 30 answers).
   The generation metrics were measured before the token cap was raised and were not re-measured.
4. **Free-tier quota.** OpenRouter free models allow roughly 50 requests per day on an account without
   purchased credits (third-party figure, to be confirmed at openrouter.ai/docs/limits). The full
   generation evaluation uses about 42 requests.
5. **Follow-up handling is heuristic** (pronoun and length based) to avoid a second LLM call per question.
6. **Chat history and metrics reset on redeploy** on a host without a persistent disk.
7. Faithfulness is checked on numbers only; there is no LLM judge.

## Files

- `backend/app/`: `core/` (config, logging), `models/` (records, API schemas), `scrapers/` (base,
  darglobal, wasalt), `ingestion/` (normalize, chunk, pipeline), `retrieval/` (embedder, bm25, query,
  hybrid), `llm/` (openrouter, prompts), `services/` (chat, guardrails, ratelimit, store), `api/routes.py`, `main.py`
- `backend/data/raw/`: `darglobal_pages.jsonl` (61 rows), `wasalt_listings.jsonl` (21 rows)
- `backend/data/processed/`: `records.jsonl`, `chunks.jsonl`, `manifest.json`
- `backend/eval/`: `dataset.jsonl` (40 questions), `run_eval.py`, `render_report.py`, `probe_retrieval.py`, `results.json`, `REPORT.md`
- `backend/tests/`: 4 test modules, 60 tests
- `frontend/src/`: `App.tsx`, `components/` (Message, Sidebar, Composer), `api.ts`, `storage.ts`, `types.ts`
- Root: `Dockerfile`, `docker-compose.yml`, `render.yaml`, `.env.example`, `README.md`, `docs/`

## Next actions, in order

1. Push to GitHub, deploy on Render, open the public URL from a different network, ask the sample questions.
2. Put the live URL in the README and the submission email, then send.
