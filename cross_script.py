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

Writes results/<doc>/gemini-deva-only.md and gemini-english-only.md, aligns the
ordered numeral sequences of the two passes (Devanagari digits folded to ASCII,
compound numerals like dates kept whole), and writes a cross-script report:
REPLACE ops — both scripts carry a numeral at the same aligned position but
disagree — are the high-signal flags (the failure class this witness exists
for); numerals present in only one script are listed as low-signal context
(bilingual forms have plenty of single-script content).
"""

import base64
import difflib
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


NUMERAL_RE = re.compile(r"\d+(?:[./-]\d+)*")   # 7, 1/2/03, 3.4.05, TM-38 -> 38


def numerals(text: str) -> list:
    """Ordered (numeral, source line) pairs; Devanagari digits folded to ASCII,
    compound numerals (dates, fractions) kept as one token."""
    items = []
    for line in text.translate(DEVA_DIGITS).splitlines():
        for m in NUMERAL_RE.finditer(line):
            items.append((m.group(0), line.strip()))
    return items


def diff_passes(deva: str, eng: str) -> dict:
    """Align the two numeral sequences; REPLACE ops are cross-script disagreements."""
    d_items, e_items = numerals(deva), numerals(eng)
    sm = difflib.SequenceMatcher(a=[n for n, _ in d_items],
                                 b=[n for n, _ in e_items], autojunk=False)
    disagreements, deva_only, eng_only, agree = [], [], [], 0
    for op, a_lo, a_hi, b_lo, b_hi in sm.get_opcodes():
        if op == "equal":
            agree += a_hi - a_lo
        elif op == "replace":
            disagreements.append({"deva": d_items[a_lo:a_hi], "eng": e_items[b_lo:b_hi]})
        elif op == "delete":
            deva_only += d_items[a_lo:a_hi]
        else:
            eng_only += e_items[b_lo:b_hi]
    return {"agree": agree, "disagreements": disagreements,
            "deva_only": deva_only, "eng_only": eng_only,
            "d_total": len(d_items), "e_total": len(e_items)}


def write_report(doc_name: str, res: dict, out_dir: Path):
    lines = [
        f"# Cross-script report — {doc_name}",
        "",
        f"Passes: `gemini-deva-only.md` vs `gemini-english-only.md` · model {MODEL}",
        f"**{res['agree']} numerals agree across scripts · "
        f"{len(res['disagreements'])} cross-script DISAGREEMENT(s) · "
        f"{len(res['deva_only'])} Devanagari-only · {len(res['eng_only'])} English-only**",
        "",
    ]
    if res["disagreements"]:
        lines += ["## Cross-script disagreements (high signal — neither reading trusted)",
                  "",
                  "| Devanagari pass | English pass |",
                  "|---|---|"]
        for d in res["disagreements"]:
            dv = "<br>".join(f"**{n}** — {l}" for n, l in d["deva"]) or "∅"
            en = "<br>".join(f"**{n}** — {l}" for n, l in d["eng"]) or "∅"
            lines.append(f"| {dv} | {en} |")
        lines.append("")
    else:
        lines += ["No cross-script disagreements.", ""]
    for label, key in (("Devanagari-only numerals (low signal)", "deva_only"),
                       ("English-only numerals (low signal)", "eng_only")):
        if res[key]:
            lines += [f"## {label}", ""]
            lines += [f"- {n} — {l}" for n, l in res[key]]
            lines.append("")
    lines += ["*A cross-script disagreement means the two scripts of the same "
              "document carry different numbers at the same position — exactly the "
              "class where combined parses harmonize to a shared (often wrong) "
              "reading. Resolve by eye, preferring whichever script's ink is "
              "legible.*"]
    (out_dir / "cross-script-report.md").write_text("\n".join(lines), encoding="utf-8")


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
        res = diff_passes(deva, eng)
        write_report(doc.name, res, out_dir)
        print(f"   {res['agree']} agree · {len(res['disagreements'])} DISAGREE · "
              f"{len(res['deva_only'])} deva-only · {len(res['eng_only'])} eng-only "
              f"-> cross-script-report.md")
        for d in res["disagreements"]:
            dv = ", ".join(n for n, _ in d["deva"]) or "∅"
            en = ", ".join(n for n, _ in d["eng"]) or "∅"
            print(f"     !! deva [{dv}]  vs  eng [{en}]")


if __name__ == "__main__":
    main()
