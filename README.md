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

## Verdict (July 2026)

| Parser | Speed/doc | Printed English | Devanagari | Handwriting |
|---|---|---|---|---|
| LiteParse 2.5.0 (local) | ~1–2s | garbled on aged scans | garbage | **missed entirely** |
| LlamaParse default | ~10–25s | clean | mostly dropped | half-caught, garbled |
| LlamaParse premium | ~14–21s | clean | **fully transcribed** | **all annotations, tagged** |

- LiteParse is not viable for aged handwritten legal documents (its own README
  recommends LlamaParse for handwriting/scans; confirmed empirically here).
- LlamaParse premium read cursive annotations, rubber-stamp dates, signature
  blocks, and full Devanagari.
- Premium costs several times more credits per page. The sensible production
  pipeline: triage with `lit is-complex` or LlamaParse default, escalate
  handwritten pages to premium.

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
