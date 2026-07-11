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

## Bottom line

**Two-tier pipeline: `gemini-3.1-flash-lite` on everything → escalate to full Gemini
Flash (or LlamaParse premium for turnkey) on any page where the cheap tier emits a
`[handwriting: ...]` tag.** The original question — "build an image classifier to
decide when premium kicks in?" — answered itself: no classifier needed. The cheap
tier reliably *tags* handwriting regions even when it misreads them; the tag is the
escalation trigger.

| Pipeline | ~Cost / 1000 pages | Notes |
|---|---|---|
| LlamaParse premium on everything | ~$45 | Turnkey, zero plumbing |
| Flash-lite + Gemini Flash escalation (~30% pages) | ~$2 | Needs retry/fallback plumbing (in `compare.py`) + a billed Gemini key |
| Ensemble: flash-lite + Mistral on every page | ~$2–3 | Disagreements flagged for human review — built (`ensemble.py`) |

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
annotation anchoring drifts and it misreads a smudged annotation. Bonus
finding, later overturned by a human check: Gemini's dissent on that smudged
annotation correctly flagged that the premium "ground truth" was wrong there —
but Gemini's own reading was wrong too (see the validation section).
Disagreement located a real error; neither reading was the truth.

## Limitations of this bake-off

- **n = 5 documents from one corpus** (one filing chain, one registry, one scan
  vintage). Scores are qualitative judgments from side-by-side reading, not
  benchmark metrics — directionally strong, statistically nothing.
- **Ground truth is itself a parser.** Outputs were judged against LlamaParse
  premium, which is imperfect: on one smudged annotation the human-checked
  truth differed from premium's reading AND Gemini's dissenting reading. Five
  fields now have human ground truth (see validation section); the rest of
  the corpus has none. Char counts measure recall-ish volume, not
  correctness.
- **Prompt parity is imperfect — partially tested.** Gemini ran with a
  purpose-written transcription prompt (tag handwriting/stamps/signatures,
  preserve Devanagari); the commercial parsers ran on their defaults. Mistral
  OCR and Reducto parse expose no prompt parameter, so parity is untestable
  there. LlamaParse does (`system_prompt_append`, via `--llama-prompted`):
  same accuracy as premium (cursive reads and the smudged annotation
  unchanged) but output now uses our `[handwriting:]`/`[stamp:]` tagging
  convention — no quality unlock, real formatting win. One tag convention
  across both pipeline tiers means the escalation trigger and downstream
  parsing are tier-agnostic.
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

## Disagreement-flagging ensemble (`ensemble.py`) — built

Mistral at $0.001/page makes a two-parser ensemble nearly free, and for legal
documents a pipeline that says "I'm unsure here" may be worth more than
another point of raw accuracy. `ensemble.py` runs two cheap independent
parsers on every document: **gemini-3.1-flash-lite as primary** (better
Devanagari, tags handwriting/stamps/signatures), **Mistral OCR as witness**.
Deterministic word-level alignment (difflib, tag-and-markdown-normalized)
locates every span where they disagree; each becomes a flagged item with both
readings. Alignment is case-, edge-punctuation- and letter-spacing-insensitive
(`NAME:` vs `NAME`, `Of` vs `OF`, `H E A D I N G` vs `HEADING` don't count as
disagreement; interior punctuation still does — `2/3` vs `23` is real);
reports always show the raw readings. Escalation verdict per doc: any
`[handwriting:]` tag in the primary, or agreement below 80%. No third model
call — the diff is the confidence signal.

Validated on the private corpus: it automatically caught both real Mistral
Devanagari misreads that had been found manually (single-word substitutions)
and isolates the cursive regions where the parsers produce different garbled
readings — including reference-number, date, and statute-year splits, exactly
the silent-poison class. All five documents correctly escalate (every one
carries annotations); the key normalization moved one document from 79.7%
agreement (tripping the threshold on pure formatting noise) to 96.2%, and cut
another from 61 flagged spans to 40 with every real disagreement retained.
The synthetic sample is the negative control: 100% agreement, no flags,
accept-cheap-tier (`sample-ensemble-report.md`).

**Escalation arbitration (`--escalate`, arbiter selectable):** flagged docs
are run through an escalation parse and every disagreement is arbitrated —
did the arbiter side with the primary, the witness, or neither? Each
disagreement's position in the arbiter's parse comes from ONE global difflib
alignment against the primary (local context search mis-anchors on
multi-letter files where near-identical boilerplate repeats — caught live
when it arbitrated one letter's date field against another letter's). Two
arbiters, cached parses consumed when present:

- `--arbiter gemini` (default): full Gemini Flash, preview fallback. Same
  family + prompt as the primary → corroboration, not independent
  adjudication. Private corpus: 70 disagreements → 27 primary / 18 witness /
  25 neither.
- `--arbiter llama`: LlamaParse premium (prompted variant first — speaks our
  tag convention). Independent family → genuine third witness; 2-of-3
  adoption is legitimate. Private corpus: 24 primary / 19 witness /
  27 neither.

The split is diagnostic: **typed-text disagreements settle** (a statute year
lands 3-of-4 across parsers; section numbers and phone/postal digits all
corroborate one side), but **handwritten numerals fan out** — with four
parses per document, a handwritten reference number and a reply-deadline
each read four different ways across the four parsers (provably illegible →
human queue), while a handwritten date gets a 2-of-4 plurality. That's the
triage the ensemble yields per field: unanimous → accept, plurality → adopt
with flag, fan-out → human. Caveats: NEITHER includes loose-anchor segments
(extra adjacent tokens), so read the escalated-reading column before trusting
a NEITHER; initials-spacing ("D.P." vs "D. P.") can still tip a verdict on
tokenization rather than substance.

**Merge-back (`--merge`):** puts every disagreement to a vote across all
available readings (primary, witness, every arbiter with a cached parse) and
composes `results/<doc>/final-transcript.md` from the primary. Vote tiers (as
revised after the human validation below): typed text with ≥3 votes adopts
silently; typed 2-vote plurality adopts with an inline flag listing
alternates; **handwriting never adopts silently** — ≥3 votes on a handwriting
span adopts with an inline `[ensemble n-of-m, handwriting]` flag, and a
handwriting plurality demotes to a full `[ensemble-review, handwriting: ...]`
tag carrying every reading and its voters. Lines no substitution touches keep
the primary's raw formatting (documents whose disagreement regions span lines
fall back to a single-stream transcript, noted in-file). Private corpus: 70
disagreements → 22 auto / 9 handwriting-flagged / 11 plurality / 28 review.
Unflagged docs pass through verbatim (`sample-final-transcript.md`).

## Human ground-truth validation (five fields)

The document owner eyeballed the five highest-stakes handwritten fields
against the originals. Epistemic status: owner-read from the same degraded
scans, not verified against the authoritative registry records — a human
reading is a stronger witness than any parser here, but it is a sixth
witness, not truth (the owner's own first read of one date was off by a
digit until document context corrected it). Results (values withheld —
client documents):

- **Fan-out → human tier validated 2/2.** Both four-readings-from-four-parsers
  fields were flagged for review, and a human could read them. Each was won
  by a *different* single parser (full Flash one, LP premium the other) — no
  parser dominates cursive.
- **The one plurality adoption was WRONG.** A cross-family 2-of-4 agreement
  (flash-lite + LP premium) adopted a handwritten date whose true value
  appeared in *no* parser's reading. Cross-family agreement on handwriting is
  not evidence.
- **A 2-2 tie hid two wrong readings** — the review flag was correct.
- **The agreed-upon-error case confirmed, in the strongest form.** On one
  smudged annotation, three parsers including premium agreed on one value,
  the lone dissenter gave another, and the human-checked truth was neither —
  even though the same number is legible on the Hindi side of the bilingual
  row. Neighbor rows cite plausible values for that field, and the models
  read what the form *should* say, then made both scripts agree with it:
  parser errors correlate through a shared language prior, not shared pixels.
  This is why consensus ≠ truth on degraded fields.

Net: the correct reading was in the candidate set on only 2 of 5 fields.
Cursive numerals are a human job; the ensemble's value is *locating* them
mechanically and supplying candidate readings.

**Bilingual cross-script witness — tested, CONFIRMED (`cross_script.py`).**
Two flash-lite passes on the bilingual form, one "transcribe only the
Devanagari" and one "only the English", so the scripts cannot harmonize each
other. On the human-validated failure field, the Devanagari-only pass read
the true value from its own ink (matching the human), while the English-only
pass kept the smudge-favored wrong value — and every other numeral row agreed
across the two passes, so a row-level cross-script numeral diff flags exactly
one field: the one every combined parse got wrong. Cost: two extra cheap-tier
calls per bilingual document. This is the first mechanism in the harness that
catches the agreed-upon-error class, and it generalizes to any document with
redundant fields (bilingual rows, totals, repeated reference numbers).

**Registry reconciliation (researched):** for registry-issued fields the
authoritative move is a lookup, not a better parse. Verdict: IP India has no
official API (CAPTCHA-gated public search; OTP-gated e-Register; no bulk
feed); WIPO's Global Brand Database covers India but contractually prohibits
automated querying; TMview covers India with no confirmed public API; the
only programmatic routes are paid aggregators (TMSearch.ai, Clarivate,
Markify — quote-gated). At small volume, registry verification is therefore a
manual step on the official public search; it becomes a pipeline stage only
with an aggregator contract.

Known limits: agreed-upon errors on typed text still carry no flag;
page-level rather than region-level escalation; votes weigh all parsers
equally though the primary and the gemini arbiter are partially correlated
(same family); 2-2 ties on typed text go to review even when sentence context
decides ("in more that/than one person") — a language-aware tie-breaker pass
is the natural next refinement.

## Layout

- `compare.py` — harness: runs each input through the selected parsers, writes
  timed side-by-side markdown to `results/<docname>/` (one file per parser
  variant); handles PDF and image inputs
- `ensemble.py` — disagreement-flagging ensemble: flash-lite primary + Mistral
  witness, word-level alignment, per-document review report with escalation
  verdict (see section above); consumes cached parses from `results/<doc>/`,
  calls the APIs only for what is missing
- `sample-ensemble-report.md` — ensemble report for the synthetic sample
  (negative control: 100% agreement, accept cheap tier)
- `sample-final-transcript.md` — merge-back output for the synthetic sample
  (unflagged → primary passes through verbatim)
- `cross_script.py` — bilingual cross-script witness: independent
  Devanagari-only and English-only passes + numeral diff (see validation
  section)
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
mode), `--llama-prompted` (premium + the Gemini transcription prompt via
`system_prompt_append`), `--gemini` (model via `GEMINI_MODEL`, default
gemini-3.5-flash), `--mistral`, `--reducto`, `--reducto-max` (agentic
enhancement), `--skip-lit`, `--skip-llama`.

Ensemble (needs `GEMINI_API_KEY` + `MISTRAL_API_KEY`; `--escalate` also uses the
cached/available arbiter parses):

```
.venv\Scripts\python ensemble.py <files...> [--escalate] [--arbiter gemini|llama] [--merge]
.venv\Scripts\python cross_script.py <files...>
```
