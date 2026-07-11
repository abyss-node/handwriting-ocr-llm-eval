"""Cross-script witness experiment: parse the Devanagari and English halves of a
bilingual document INDEPENDENTLY, so the two scripts cannot harmonize each other.

Motivation (human-validated failure): every parser misread a smudged bilingual
row identically on BOTH scripts, even though one script's ink is legible. The
errors correlate through a shared language prior — the combined parse makes the
scripts agree. Hypothesis (CONFIRMED on the corpus): a single-script pass is
anchored on that script's own pixels and escapes the harmonization; diffing
numerals across the two passes flags exactly this failure class, and only it.

Usage:
    python cross_script.py <file1> [file2 ...]

Writes results/<doc>/gemini-deva-only.md and gemini-english-only.md, then prints
a numeral-level diff of the two passes (digits normalized, Devanagari digits
folded to ASCII).
"""

import base64
import re
import sys
import time
from pathlib import Path

import requests

import compare  # .env, MIME map

HERE = Path(__file__).parent
RESULTS = HERE / "results"
MODEL = "gemini-3.1-flash-lite"

DEVA_PROMPT = (
    "Transcribe ONLY the Devanagari (Hindi) text in this document — printed and "
    "handwritten — exactly as written, in reading order. Include numerals only when "
    "they are part of a Hindi text run (e.g. a Hindi label followed by a number). "
    "Do NOT transcribe, translate, or consult any English/Latin text on the page: "
    "read the Devanagari from the ink itself, even where English text nearby appears "
    "to say something different. If a word or numeral is unclear, transcribe what the "
    "strokes show and append (?). Output plain text, one line per text region."
)

ENG_PROMPT = (
    "Transcribe ONLY the English (Latin-script) text in this document — printed and "
    "handwritten — exactly as written, in reading order. Do NOT transcribe, translate, "
    "or consult any Hindi/Devanagari text on the page: read the English from the ink "
    "itself, even where Hindi text nearby appears to say something different. If a word "
    "or numeral is unclear, transcribe what the strokes show and append (?). Output "
    "plain text, one line per text region."
)

DEVA_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")


def call_gemini(doc: Path, prompt: str, out_file: Path) -> str:
    for attempt in range(5):
        resp = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent",
            headers={"x-goog-api-key": compare.os.environ["GEMINI_API_KEY"]},
            json={"contents": [{"parts": [
                {"inline_data": {"mime_type": compare.MIME[doc.suffix.lower()],
                                 "data": base64.b64encode(doc.read_bytes()).decode()}},
                {"text": prompt},
            ]}]},
            timeout=600,
        )
        if resp.status_code in (429, 503) and attempt < 4:
            wait = 20 * (attempt + 1)
            print(f"    {resp.status_code}, retrying in {wait}s...")
            time.sleep(wait)
            continue
        break
    resp.raise_for_status()
    body = resp.json()
    text = "".join(p.get("text", "") for p in body["candidates"][0]["content"]["parts"])
    if not text:
        raise RuntimeError(f"empty response: {str(body)[:300]}")
    out_file.write_text(text, encoding="utf-8")
    return text


def numbered_lines(text: str) -> list:
    """Lines that contain a numeral, with Devanagari digits folded to ASCII."""
    out = []
    for line in text.translate(DEVA_DIGITS).splitlines():
        if re.search(r"\d", line):
            out.append(line.strip())
    return out


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    for f in sys.argv[1:]:
        doc = Path(f).resolve()
        out_dir = RESULTS / doc.stem
        out_dir.mkdir(parents=True, exist_ok=True)
        print(f"== {doc.name}")
        deva_f = out_dir / "gemini-deva-only.md"
        eng_f = out_dir / "gemini-english-only.md"
        deva = deva_f.read_text(encoding="utf-8") if deva_f.exists() else \
            call_gemini(doc, DEVA_PROMPT, deva_f)
        eng = eng_f.read_text(encoding="utf-8") if eng_f.exists() else \
            call_gemini(doc, ENG_PROMPT, eng_f)
        print("-- Devanagari-only pass, lines containing numerals:")
        for l in numbered_lines(deva):
            print(f"   {l}")
        print("-- English-only pass, lines containing numerals:")
        for l in numbered_lines(eng):
            print(f"   {l}")


if __name__ == "__main__":
    main()
