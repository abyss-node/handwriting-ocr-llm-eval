# Handwriting OCR / LLM parsing eval

Side-by-side evaluation harness for document parsers on a hard real-world case:
aged, bilingual (Hindi/English) scanned legal forms with cursive handwritten
examiner annotations, rubber stamps, and signature blocks — 1986-era Indian
trademark-registry correspondence.

Parsers covered:

- **LiteParse** ([run-llama/liteparse](https://github.com/run-llama/liteparse)) — local, Tesseract-based
- **LlamaParse** — cloud; default, premium, and agentic (`parse_page_with_agent`) modes
- **Gemini** — direct API with a structured transcription prompt (tags `[handwriting: ...]`, `[stamp: ...]`, `[signature: ...]`, preserves Devanagari verbatim)
- **Mistral OCR** (`mistral-ocr-latest`)
- **Reducto** — default and agentic-enhancement modes

## Verdict (July 2026, full bake-off)

| Parser | Score | Notes |
|---|---|---|
| **Gemini Flash** | **8.5–9/10** | Quality winner. The only parser to transcribe the cursive annotations correctly, and it caught a likely transcription error in LlamaParse premium's output. |
| LlamaParse premium | 8.5/10 | Full Devanagari, all handwriting tagged `[handwriting: ...]`, stamps, signatures. Several times more credits/page than default. |
| LlamaParse agentic | 8/10 | Right words, but strikethrough/correction rendering comes out unanchored. |
| Mistral OCR | 7.5/10 | Cheap-tier winner: ~$0.001/page, 3–5s, near-premium bilingual Devanagari. Handwriting garbled. |
| Reducto (default = agentic) | 6.5/10 | Agentic mode made Devanagari *worse* and describes signatures in prose instead of transcribing. |
| LlamaParse default | 6/10 | Clean typed English, but drops ALL Hindi silently. |
| LiteParse 2.5.0 (local) | 2/10 | Corrupts even typed dates; misses handwriting entirely. Not viable for aged scans (its own README says so; confirmed empirically). |

Recommended pipeline: **Mistral OCR as the cheap tier, escalate to Gemini Flash**
(with retry + model fallback — Flash 503s on very large PDFs) for handwritten or
low-confidence pages. LlamaParse premium if you want turnkey instead of
prompt-managed.

## Layout

- `compare.py` — the harness: runs each input through every enabled parser,
  writes timed side-by-side markdown to `results/<docname>/` plus a
  `summary.md` timing table
- `sample-handwriting.png` — synthetic smoke-test image (Ink Free font), so
  the harness can be exercised without the source documents

The evaluation source documents were client-provided and are not included in
this repository.

## Setup

```
python -m venv .venv
.venv\Scripts\pip install liteparse llama-cloud-services python-dotenv requests
winget install ImageMagick.ImageMagick   # liteparse needs it for image/PDF conversion
```

Put API keys in `.env` next to `compare.py` (only the ones you use):

```
LLAMA_CLOUD_API_KEY=llx-...
GEMINI_API_KEY=...
MISTRAL_API_KEY=...
REDUCTO_API_KEY=...
```

Run:

```
.venv\Scripts\python compare.py <files...> --premium --gemini --mistral
```
