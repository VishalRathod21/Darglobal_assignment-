# Interview Notes: how to explain PropIntel AI

One section per component: what it is, why it was built this way, and a short answer you can say out loud.

## 30-second project pitch

"I built a RAG assistant over two public real estate sites. An offline pipeline scrapes, normalises and
indexes the data; at request time I run vector search and BM25 together, fuse them with Reciprocal Rank
Fusion, and send the top passages to a free OpenRouter model with a strict grounding prompt. If retrieval is
weak the system refuses without calling the model, and every citation is checked after generation. It runs
as one Docker container that fits a 512 MB free tier."

## 1. Scraping

- **What:** Two scrapers behind shared utilities. DarGlobal uses Playwright; Wasalt uses httpx.
- **Why different tools:** I inspected both sites first. DarGlobal returns an empty JavaScript challenge to
  plain HTTP, so it needs a real browser. Wasalt is Next.js and embeds its data as JSON in the page
  (`__NEXT_DATA__`), so a browser is unnecessary.
- **Why parse JSON instead of CSS selectors:** selectors break when the design changes; the embedded JSON is
  the site's own data contract.
- **Compliance:** robots.txt is checked per URL, Wasalt's llms.txt is followed (no search pages, no contact
  details), and a block stops the crawl.
- **Say this:** "I inspect before I write selectors. Where the site ships structured JSON I parse that. I
  treat robots.txt and a 403 as hard limits: Wasalt's Cloudflare challenged my client, so I stopped,
  documented it, and added an offline parser for saved pages instead of trying to get around it."
- **Likely follow-up:** "Why so few Wasalt listings?" Answer honestly: access was blocked, coverage is 21
  real listings, and the pipeline scales the moment more pages are available.

## 2. Normalisation and deduplication

- **What:** Every source row becomes one `Record` Pydantic model with the same fields (source, type, URL,
  title, text, city, price, bedrooms, scraped_at, content hash).
- **Why:** Everything downstream handles one shape. Adding a third website means writing one normaliser.
- **Dedup:** by id (same page twice) and by body text (same content under two URLs).
- **Say this:** "The scraper layer is allowed to be messy. The contract starts at the Record model."

## 3. Chunking

- **What:** Listings become one self-contained card each. Long pages are split into about 1,000-character
  windows on line boundaries, with a one-line overlap, and every chunk starts with a header naming the
  document and its location.
- **Why two strategies:** splitting a listing separates the price from the bedrooms. For prose, a chunk
  that says "Amenities: gym, pool" is useless unless it also says which project it belongs to.
- **Say this:** "Chunking follows document shape, not a fixed token count. The contextual header was the
  single biggest retrieval improvement."

## 4. Embeddings and vector store

- **What:** `bge-small-en-v1.5` through FastEmbed (ONNX), stored in embedded ChromaDB with cosine distance.
- **Why FastEmbed:** same model weights as sentence-transformers without PyTorch. The whole app uses about
  290 MB, which fits a 512 MB container.
- **Why Chroma over FAISS:** metadata filtering and persistence come built in; FAISS needs a separate
  metadata store.
- **Incremental ingestion:** each chunk stores its record's content hash. A re-run embeds only new or
  changed chunks and deletes chunks whose record disappeared. `scraped_at` is excluded from the hash,
  otherwise every re-scrape would re-embed everything.
- **Say this:** "The index is derived data. I rebuild it inside the Docker image, so the container needs no
  persistent disk and never downloads a model at runtime."

## 5. Hybrid retrieval and RRF

- **What:** Top 20 from vectors, top 20 from BM25, fused by rank: `score = sum(1 / (60 + rank))`.
- **Why hybrid:** embeddings understand meaning but blur exact tokens like "DG1" or "Al-Mahdiyah". BM25
  matches exact terms but not paraphrases.
- **Why RRF and not a weighted sum:** cosine is 0 to 1 and BM25 is unbounded, so a weighted sum needs
  tuning per corpus. RRF only uses ranks.
- **Honest result:** on my test set hybrid has the best recall and precision; vector-only has a slightly
  higher MRR. The gain comes mainly from listing queries with numeric limits. I report that as measured.
- **Say this:** "I ran an ablation instead of assuming hybrid is better. It is better on recall and
  precision here, and I can show where."

## 6. Metadata filtering

- **What:** Rule-based extraction of source, sale or rent, bedrooms and price limits from the question.
- **Design decision:** only constraints an embedding cannot express (numbers, sale versus rent) become hard
  filters. A city name alone is left to hybrid search, because filtering on it hid press releases that
  mention the city but have no city field.
- **Fallback:** if no listing satisfies every constraint, filters are relaxed and the prompt tells the model
  to say there is no exact match.
- **Why rules, not an LLM:** the free tier has a daily request cap; a second model call per question would
  halve capacity.

## 7. Hallucination prevention

Four layers, because no single one is reliable:

1. **Relevance gate:** best cosine similarity below 0.62 means no LLM call and a fixed "I don't have that" reply.
2. **Grounding prompt:** answer only from numbered passages, cite every fact, keep sources separate.
3. **Citation validation:** a `[7]` when six passages were sent is removed.
4. **Refusal detection:** if the model says it lacks the information, the response is marked `unknown` and no sources are shown.

- **How the threshold was set:** I measured similarity for in-scope and out-of-scope questions; relevant
  ones scored 0.74 or more, unrelated ones 0.61 or less.
- **Say this:** "The cheapest hallucination to prevent is the one where the model is never called."

## 8. Prompt injection

- Input patterns block obvious override attempts before retrieval.
- Retrieved text is wrapped in `<context>` tags and the system prompt declares it untrusted data.
- Output citations are validated.
- **Say this:** "Pattern matching alone is easy to bypass, so it is one layer of several. The scraped pages
  are also an injection surface, which is why context is delimited and declared untrusted."

## 9. OpenRouter client

- **What:** An ordered chain of free models. Each gets one retry on transient errors (timeout, 429, 5xx)
  with backoff. Permanent errors (404 model removed) skip to the next model. Auth errors fail fast.
- **Degraded mode:** if the whole chain fails, the API still returns 200 with the top retrieved passages.
- **Say this:** "Free models disappear and rate-limit without notice. I classify errors into retry, skip
  and stop, and the user never sees a 500 because the provider had a bad minute."

## 10. Conversation memory, cache, rate limit

- **Memory:** last three turns go to the model; follow-up questions also reuse the previous user question
  for retrieval.
- **Cache:** only first-turn questions are cached, because a follow-up's meaning depends on its history.
- **Rate limit:** sliding window per client IP, in memory. With several replicas it would move to Redis.
- **SQLite:** one container, small rows. Say plainly that you would switch to Postgres and Redis when
  there is more than one instance.

## 11. Observability

- JSON logs, one object per line, with a request id.
- Each chat request records retrieval time, LLM time, total time, tokens, model and outcome.
- `/api/admin/metrics` gives p50 and p95 latency, token totals, cache hits and outcome counts.

## 12. Docker and deployment

- Multi-stage build: Node builds the UI, Python serves it. One container, one URL, no CORS.
- Index and embedding model are baked in at build time.
- Non-root user, health check, `$PORT` from the platform, one worker to stay within memory.
- **Say this:** "I tested the container locally with the same 512 MB limit as the free tier, so memory
  problems would show up before deployment."

## 13. Evaluation

- 40 questions across six categories. Retrieval is scored without the LLM, so it is free and repeatable.
- Generation is scored on outcome accuracy, fact coverage, citation correctness, numeric faithfulness and
  hallucination rate.
- **Say this:** "The report is generated from the results file, so no number is typed by hand, and it
  lists its own limits: small test set, written by me, numeric faithfulness only."

## Questions to expect

| Question | Short answer |
|---|---|
| Why not LangChain? | The pipeline is about 300 lines of plain Python. Fewer dependencies, every step is testable and visible. |
| How would you scale this? | Move the index to Qdrant or pgvector, state to Postgres and Redis, run ingestion as a scheduled job, add several API replicas. |
| How do you keep data fresh? | Re-run scrapers on a schedule; the content hash makes re-ingestion cheap; `scraped_at` is shown to users. |
| What would you add next? | A cross-encoder reranker if precision becomes a problem, LLM-based query rewriting for follow-ups, streaming responses, Arabic content. |
| Biggest weakness? | Wasalt coverage, and follow-up handling is heuristic. |
