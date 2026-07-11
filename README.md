# Handwriting OCR / LLM parsing eval

Side-by-side evaluation of document parsers on a hard real-world case: aged,
bilingual (Hindi/English) scanned legal forms with cursive handwritten examiner
annotations, rubber stamps, and signature blocks — 1986-era Indian
trademark-registry correspondence. Plus a replication of a published
Devanagari OCR benchmark to cross-check the qualitative findings.

Contenders: [run-llama/liteparse](https://github.com/run-llama/liteparse)
(local Tesseract), LlamaParse (default / premium / agentic), Gemini direct API,
Mistral OCR, Reducto (default / agentic).

> **Note:** this is a sanitized public mirror of a private evaluation repo.
> The source documents were client-provided, so they, all parser outputs
> derived from them, and document-content specifics in this README are
> excluded. The harness, methodology, scores, and the public-dataset
> benchmark replication are complete.

## Verdict (July 2026 bake-off)

| Parser | Score | Speed/doc | ~$/page | Notes |
|---|---|---|---|---|
| Gemini Flash (direct) | **8.5–9** | 30–120s | ~0.003 | Quality winner: only parser to read the cursive fully correctly; needs retry + model-fallback plumbing (503s on largest doc) |
| LlamaParse premium | 8.5 | 14–21s | ~0.045 | Turnkey benchmark: full Devanagari, tagged + anchored `[handwriting: ...]` |
| LlamaParse agentic | 8 | 10–20s | ~0.09 | Premium-grade text but handwriting rendered as unanchored strikethrough — not worth 2× premium |
| Mistral OCR | 7.5 | 3–5s | 0.001 | Cheap-tier winner: full bilingual Devanagari near premium; cursive garbled |
| Reducto (default & agentic) | 6.5 | 10–57s | — | Devanagari has char-level typos; agentic mode made Hindi worse and describes signatures instead of transcribing |
| LlamaParse default | 6 | 10–25s | ~0.003 | Clean typed English but silently drops ALL Hindi |
| LiteParse (local) | 2 | 1–2s | free | Corrupts even typed dates; disqualified |
| Gemini 3.1 Pro | untested | — | — | Free-tier quota is 0; `run-pro.ps1` runs the sweep once the key is billed |

**Recommended pipeline (updated after the flash-lite test):** gemini-3.1-flash-lite
on everything (took the cheap tier from Mistral: similar Devanagari, plus
handwriting/stamp/signature tagging, crossed-out-text marking, 4–10s/doc),
escalating annotated pages to full Gemini Flash — or LlamaParse premium for
turnkey. Flash-lite scores ~7.5–8/10 here: cursive is where the lite tier shows —
annotation anchoring drifts and it misreads a smudged annotation that full
Flash likely gets right. Bonus finding: Gemini flagged a likely transcription
error in the LlamaParse-premium output used as ground truth.

## Limitations of this bake-off

- **n = 5 documents from one corpus** (one filing chain, one registry, one scan
  vintage). Scores are qualitative judgments from side-by-side reading, not
  benchmark metrics — directionally strong, statistically nothing.
- **Ground truth is itself a parser.** Outputs were judged against LlamaParse
  premium, which is imperfect: on one smudged annotation Gemini's reading is
  probably right and premium's probably wrong. No human transcription exists
  for these documents. Char counts measure recall-ish volume, not correctness.
- **Prompt parity is imperfect.** Gemini ran with a purpose-written
  transcription prompt (tag handwriting/stamps/signatures, preserve
  Devanagari); the commercial parsers ran on their defaults. Some of Gemini's
  edge is prompt, not model.
- **Gemini operational caveats:** free-tier `gemini-3.5-flash` 503'd 9/9 times
  on the largest doc (worked on `gemini-3-flash-preview`);
  `gemini-3.1-pro-preview` is untestable on a free key (quota limit is 0 —
  needs Cloud Billing on the key, which is separate from a Google AI Pro
  consumer subscription). Production use of direct Gemini requires retry +
  model-fallback plumbing (now in `compare.py`).
- **Reducto's result is not a trial-tier or settings artifact.** Verified by
  rerunning the worst document with explicit `settings.ocr_system: "standard"`
  (their multilingual engine, the only value the current API accepts; Hindi
  officially supported) — output near-identical to the default run, same
  Devanagari typos. Trial uses the same models as paid (differences are
  compliance/rate limits). The weakness is architectural: pipeline OCR for
  text + VLM only for layout/figures, so degraded Devanagari gets
  character-level OCR errors that end-to-end VLM parsers avoid. No public
  Devanagari benchmark for Reducto exists to compare against.
- **Timings are single-shot** on a home connection, include retries, and for
  cloud services reflect queue conditions on the day.
- `llama-cloud-services` is deprecated (EOL May 2026) — migrate to
  `llama-cloud>=1.0` before reusing the LlamaParse path.

## Untested candidates (and why)

- **Claude vision (direct API)** — #2 on the real-Devanagari stress test
  ([arXiv 2606.29213](https://arxiv.org/html/2606.29213v1)), the only untested
  model that might beat Gemini Flash outright. Skipped for lack of an
  Anthropic API key.
- **Chandra (Datalab)** — best open-weights doc model (83.1 olmOCR-Bench,
  handwriting support). Unproven on Devanagari, needs a 16GB GPU (or their
  hosted API), but it is the only self-hostable option — relevant if
  confidential documents must not leave the premises.
- **Google Document AI** — enterprise handwriting API; likely a lateral move
  from Gemini with far more setup (GCP project/processor). Only worth it for
  SLA needs.
- **Rejected on evidence:** GPT-5.x vision (58.5 on real Devanagari — below
  EasyOCR), olmOCR / DeepSeek-OCR (collapse on real Devanagari scans), AWS
  Textract (no Hindi).

## Published-benchmark cross-check

`bench_real.py` replicates the real-scan set from the arXiv Devanagari stress
test ([repo](https://github.com/Aditya-PS-05/devanagari-ocr-benchmark): first
300 valid train examples of Process-Venue/Sanskrit-OCR-Typed-Dataset) and
scores with its metrics. Full 300 images, chrF++ as deva-only (raw): deva-only
strips wrapper prose; raw matches the paper's protocol.

| Parser | n | chrF++ | med CER | Notes |
|---|---|---|---|---|
| gemini-3-flash-preview | 17 | 96.6 (95.6) | 0.000 | Best in field, but tiny n — daily preview quota is ~20 req |
| **gemini-3.1-flash-lite** | 300 | **88.4 (84.6)** | 0.000 | A *lite* model matching the paper's frontier best (Gemini 2.5 Flash, 86.3 raw) |
| Mistral OCR (latest) | 300 | 83.2 (76.0) | 0.000 | **Raw 76.0 vs the paper's published 77.6 — near-exact replication, validating this harness.** 2.7% catastrophic repetition blow-ups (the paper's known Mistral failure mode) |
| Reducto | 300 | 67.1 (28.1) | 0.062 | ~10–14% char errors, stable across sample size; wraps output in English descriptions, hence the raw collapse |
| LlamaParse premium | 50 | 0.0 | 1.0 | `NO_CONTENT_HERE` on word crops — page-parser confound the paper flags; not extended to 300 (burns credits documenting an artifact) |

Replication caveats: model versions differ from the paper's eval
(gemini-2.5-flash is retired for new API users — 404 — so the paper's exact
winner is unrunnable); free-tier daily caps (3.5-flash and 3-flash-preview
≈ 20 req/day) blocked the strong Gemini models — the 3-flash-preview row can
be topped up across days or with a billed key.

Parser outputs are not committed (regenerate with `bench_real.py build` then
`bench_real.py run <parser> -n 300`).

## Next idea: disagreement-flagging ensemble

Mistral at $0.001/page makes a two-parser ensemble nearly free: run Mistral +
Gemini on every page, reconcile with a cheap model, and flag disagreements
(like the smudged-annotation split above) for human review instead of silently
picking one reading. For legal documents, a pipeline that says "I'm unsure
here" may be worth more than another point of raw accuracy.

## Layout

- `compare.py` — harness: runs each input through the selected parsers, writes
  timed side-by-side markdown to `results/<docname>/` (one file per parser
  variant); handles PDF and image inputs
- `bench_real.py` — builds the published-benchmark real set (public dataset),
  runs any parser over it, scores chrF++ / CER with the paper's protocol
- `run-pro.ps1` — probes Gemini 3.1 Pro quota and runs the full sweep if
  available
- `sample-handwriting.png` — synthetic smoke-test image (Ink Free font,
  fictional text). All seven cloud parser variants transcribe it perfectly and
  near-identically; only LiteParse fails (`sample-out.md` — "14+ ... 1462",
  "Vewdor"). Confirms the synthetic-vs-real gap: Reducto is flawless here yet
  scrambles real 1986 cursive — synthetic samples can disqualify a parser,
  never qualify one.

The evaluation source documents were client-provided and are not included in
this repository, nor are any parser outputs derived from them.

## Setup

```
python -m venv .venv
.venv\Scripts\pip install liteparse llama-cloud-services python-dotenv requests
.venv\Scripts\pip install datasets sacrebleu   # only for bench_real.py
winget install ImageMagick.ImageMagick         # liteparse needs it for image/PDF conversion
```

`.env` keys (only for the parsers you invoke): `LLAMA_CLOUD_API_KEY`,
`GEMINI_API_KEY`, `MISTRAL_API_KEY`, `REDUCTO_API_KEY`.

```
.venv\Scripts\python compare.py <files...> --premium --gemini --mistral --reducto
```

Flags: `--premium` (LlamaParse premium), `--llama-agentic` (top LlamaParse
mode), `--gemini` (model via `GEMINI_MODEL`, default gemini-3.5-flash),
`--mistral`, `--reducto`, `--reducto-max` (agentic enhancement), `--skip-lit`,
`--skip-llama`.
