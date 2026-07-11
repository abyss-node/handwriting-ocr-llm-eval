"""Side-by-side comparison: LiteParse (local) vs LlamaParse (cloud) vs Gemini vs Mistral OCR.

Usage:
    python compare.py <file1> [file2 ...] [--premium] [--gemini] [--mistral]

Keys in .env next to this script: LLAMA_CLOUD_API_KEY, GEMINI_API_KEY, MISTRAL_API_KEY.
Results land in results/<docname>/ as <parser>.md, plus a timing summary.
"""

import argparse
import base64
import os
import subprocess
import sys
import time
from pathlib import Path

import requests

from dotenv import load_dotenv

HERE = Path(__file__).parent
LIT = HERE / ".venv" / "Scripts" / "lit.exe"
RESULTS = HERE / "results"

load_dotenv(HERE / ".env")

# lit needs ImageMagick for image inputs; winget install doesn't reach every shell's PATH
for magick_dir in Path("C:/Program Files").glob("ImageMagick*"):
    os.environ["PATH"] = f"{magick_dir};{os.environ['PATH']}"
    break


def run_liteparse(doc: Path, out_dir: Path) -> dict:
    out_file = out_dir / "liteparse.md"
    start = time.perf_counter()
    proc = subprocess.run(
        [str(LIT), "parse", str(doc), "--format", "markdown", "-o", str(out_file)],
        capture_output=True, text=True,
    )
    elapsed = time.perf_counter() - start
    ok = proc.returncode == 0 and out_file.exists()
    return {
        "parser": "liteparse",
        "ok": ok,
        "seconds": round(elapsed, 1),
        "chars": len(out_file.read_text(encoding="utf-8", errors="replace")) if ok else 0,
        "error": proc.stderr.strip() if not ok else "",
    }


def run_llamaparse(doc: Path, out_dir: Path, premium: bool, agentic: bool = False,
                   prompted: bool = False) -> dict:
    from llama_cloud_services import LlamaParse

    tier = ("-prompted" if prompted else
            "-agentic" if agentic else
            "-premium" if premium else "")
    out_file = out_dir / f"llamaparse{tier}.md"
    if prompted:
        parser = LlamaParse(result_type="markdown", premium_mode=True,
                            system_prompt_append=GEMINI_PROMPT, verbose=False)
    elif agentic:
        parser = LlamaParse(result_type="markdown", parse_mode="parse_page_with_agent",
                            verbose=False)
    else:
        parser = LlamaParse(result_type="markdown", premium_mode=premium, verbose=False)
    start = time.perf_counter()
    try:
        docs = parser.load_data(str(doc))
        text = "\n\n---\n\n".join(d.text for d in docs)
        out_file.write_text(text, encoding="utf-8")
        elapsed = time.perf_counter() - start
        return {
            "parser": f"llamaparse{tier}",
            "ok": True,
            "seconds": round(elapsed, 1),
            "chars": len(text),
            "error": "",
        }
    except Exception as e:
        return {
            "parser": f"llamaparse{tier}",
            "ok": False,
            "seconds": round(time.perf_counter() - start, 1),
            "chars": 0,
            "error": str(e),
        }


MIME = {".pdf": "application/pdf", ".png": "image/png", ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg", ".webp": "image/webp"}

GEMINI_PROMPT = """Transcribe this scanned document to markdown, completely and faithfully.
- Transcribe ALL text: typed, printed, and handwritten. Do not summarize or skip anything.
- Tag handwritten text as [handwriting: ...], stamps as [stamp: ...], signatures as [signature: ...].
- Preserve Hindi/Devanagari text verbatim in Devanagari script; do not transliterate or translate.
- Preserve form structure (fields, tables) in markdown.
- Separate pages with a horizontal rule (---).
Output only the markdown transcription, no commentary."""


def run_gemini(doc: Path, out_dir: Path) -> dict:
    model = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash")
    out_file = out_dir / ("gemini.md" if model == "gemini-3.5-flash" else f"{model}.md")
    start = time.perf_counter()
    try:
        for attempt in range(5):
            resp = requests.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                headers={"x-goog-api-key": os.environ["GEMINI_API_KEY"]},
                json={"contents": [{"parts": [
                    {"inline_data": {"mime_type": MIME[doc.suffix.lower()],
                                     "data": base64.b64encode(doc.read_bytes()).decode()}},
                    {"text": GEMINI_PROMPT},
                ]}]},
                timeout=600,
            )
            if resp.status_code in (429, 503) and attempt < 4:
                wait = 20 * (attempt + 1)
                print(f"    gemini {resp.status_code}, retrying in {wait}s...")
                time.sleep(wait)
                continue
            break
        resp.raise_for_status()
        body = resp.json()
        text = "".join(p.get("text", "") for p in body["candidates"][0]["content"]["parts"])
        if not text:
            raise RuntimeError(f"empty response: {str(body)[:300]}")
        out_file.write_text(text, encoding="utf-8")
        return {"parser": f"gemini ({model})", "ok": True,
                "seconds": round(time.perf_counter() - start, 1), "chars": len(text), "error": ""}
    except Exception as e:
        detail = getattr(getattr(e, "response", None), "text", "") or str(e)
        return {"parser": f"gemini ({model})", "ok": False,
                "seconds": round(time.perf_counter() - start, 1), "chars": 0, "error": detail[:300]}


def run_mistral(doc: Path, out_dir: Path) -> dict:
    out_file = out_dir / "mistral-ocr.md"
    start = time.perf_counter()
    try:
        resp = requests.post(
            "https://api.mistral.ai/v1/ocr",
            headers={"Authorization": f"Bearer {os.environ['MISTRAL_API_KEY']}"},
            json={"model": "mistral-ocr-latest",
                  "document": (
                      {"type": "image_url",
                       "image_url": f"data:{MIME[doc.suffix.lower()]};base64,"
                                    + base64.b64encode(doc.read_bytes()).decode()}
                      if doc.suffix.lower() != ".pdf" else
                      {"type": "document_url",
                       "document_url": "data:application/pdf;base64,"
                                       + base64.b64encode(doc.read_bytes()).decode()})},
            timeout=600,
        )
        resp.raise_for_status()
        text = "\n\n---\n\n".join(p.get("markdown", "") for p in resp.json()["pages"])
        out_file.write_text(text, encoding="utf-8")
        return {"parser": "mistral-ocr", "ok": True,
                "seconds": round(time.perf_counter() - start, 1), "chars": len(text), "error": ""}
    except Exception as e:
        detail = getattr(getattr(e, "response", None), "text", "") or str(e)
        return {"parser": "mistral-ocr", "ok": False,
                "seconds": round(time.perf_counter() - start, 1), "chars": 0, "error": detail[:300]}


def run_reducto(doc: Path, out_dir: Path, agentic: bool = False) -> dict:
    out_file = out_dir / ("reducto-agentic.md" if agentic else "reducto.md")
    name = "reducto-agentic" if agentic else "reducto"
    headers = {"Authorization": f"Bearer {os.environ['REDUCTO_API_KEY']}"}
    start = time.perf_counter()
    try:
        with doc.open("rb") as fh:
            up = requests.post("https://platform.reducto.ai/upload",
                               headers=headers, files={"file": (doc.name, fh)}, timeout=120)
        up.raise_for_status()
        body = {"input": f"reducto://{up.json()['file_id']}"}
        if agentic:
            body["enhance"] = {"agentic": [{"scope": "text"}, {"scope": "table"},
                                           {"scope": "figure"}]}
        resp = requests.post("https://platform.reducto.ai/parse", headers=headers,
                             json=body, timeout=600)
        resp.raise_for_status()
        result = resp.json()["result"]
        if result.get("type") == "url":
            result = requests.get(result["url"], timeout=120).json()
        text = "\n\n---\n\n".join(c.get("content", "") for c in result["chunks"])
        out_file.write_text(text, encoding="utf-8")
        return {"parser": name, "ok": True,
                "seconds": round(time.perf_counter() - start, 1), "chars": len(text), "error": ""}
    except Exception as e:
        detail = getattr(getattr(e, "response", None), "text", "") or str(e)
        return {"parser": name, "ok": False,
                "seconds": round(time.perf_counter() - start, 1), "chars": 0, "error": detail[:300]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    ap.add_argument("--premium", action="store_true",
                    help="also run LlamaParse premium mode (better for handwriting, costs more credits)")
    ap.add_argument("--skip-llama", action="store_true", help="only run liteparse")
    ap.add_argument("--skip-lit", action="store_true", help="skip the local liteparse run")
    ap.add_argument("--gemini", action="store_true",
                    help="also parse with Gemini direct API (needs GEMINI_API_KEY)")
    ap.add_argument("--mistral", action="store_true",
                    help="also parse with Mistral OCR (needs MISTRAL_API_KEY)")
    ap.add_argument("--reducto", action="store_true",
                    help="also parse with Reducto (needs REDUCTO_API_KEY)")
    ap.add_argument("--reducto-max", action="store_true",
                    help="Reducto with agentic enhancement on all scopes (costs more)")
    ap.add_argument("--llama-agentic", action="store_true",
                    help="LlamaParse top agentic mode, parse_page_with_agent (costs more)")
    ap.add_argument("--llama-prompted", action="store_true",
                    help="LlamaParse premium with the Gemini transcription prompt appended")
    args = ap.parse_args()

    for flag, key in (("gemini", "GEMINI_API_KEY"), ("mistral", "MISTRAL_API_KEY"),
                      ("reducto", "REDUCTO_API_KEY"), ("reducto_max", "REDUCTO_API_KEY")):
        if getattr(args, flag) and not os.environ.get(key):
            sys.exit(f"--{flag.replace('_', '-')} requires {key} in .env or the environment")

    rows = []
    for f in args.files:
        doc = Path(f).resolve()
        if not doc.exists():
            print(f"SKIP (not found): {doc}")
            continue
        out_dir = RESULTS / doc.stem
        out_dir.mkdir(parents=True, exist_ok=True)
        print(f"\n=== {doc.name} ===")

        if not args.skip_lit:
            r = run_liteparse(doc, out_dir)
            rows.append((doc.name, r))
            print(f"  liteparse: {'OK' if r['ok'] else 'FAIL'} {r['seconds']}s {r['chars']} chars {r['error'][:200]}")

        if not args.skip_llama:
            r = run_llamaparse(doc, out_dir, premium=False)
            rows.append((doc.name, r))
            print(f"  llamaparse: {'OK' if r['ok'] else 'FAIL'} {r['seconds']}s {r['chars']} chars {r['error'][:200]}")
            if args.premium:
                r = run_llamaparse(doc, out_dir, premium=True)
                rows.append((doc.name, r))
                print(f"  llamaparse-premium: {'OK' if r['ok'] else 'FAIL'} {r['seconds']}s {r['chars']} chars {r['error'][:200]}")

        if args.gemini:
            r = run_gemini(doc, out_dir)
            rows.append((doc.name, r))
            print(f"  {r['parser']}: {'OK' if r['ok'] else 'FAIL'} {r['seconds']}s {r['chars']} chars {r['error'][:200]}")

        if args.mistral:
            r = run_mistral(doc, out_dir)
            rows.append((doc.name, r))
            print(f"  mistral-ocr: {'OK' if r['ok'] else 'FAIL'} {r['seconds']}s {r['chars']} chars {r['error'][:200]}")

        if args.reducto:
            r = run_reducto(doc, out_dir)
            rows.append((doc.name, r))
            print(f"  reducto: {'OK' if r['ok'] else 'FAIL'} {r['seconds']}s {r['chars']} chars {r['error'][:200]}")

        if args.reducto_max:
            r = run_reducto(doc, out_dir, agentic=True)
            rows.append((doc.name, r))
            print(f"  reducto-agentic: {'OK' if r['ok'] else 'FAIL'} {r['seconds']}s {r['chars']} chars {r['error'][:200]}")

        if args.llama_agentic:
            r = run_llamaparse(doc, out_dir, premium=False, agentic=True)
            rows.append((doc.name, r))
            print(f"  llamaparse-agentic: {'OK' if r['ok'] else 'FAIL'} {r['seconds']}s {r['chars']} chars {r['error'][:200]}")

        if args.llama_prompted:
            r = run_llamaparse(doc, out_dir, premium=True, prompted=True)
            rows.append((doc.name, r))
            print(f"  llamaparse-prompted: {'OK' if r['ok'] else 'FAIL'} {r['seconds']}s {r['chars']} chars {r['error'][:200]}")

    summary = RESULTS / "summary-runs.md"
    lines = ["", f"## run: {time.strftime('%Y-%m-%d %H:%M')}", "",
             "| document | parser | ok | seconds | chars |", "|---|---|---|---|---|"]
    lines += [f"| {name} | {r['parser']} | {'yes' if r['ok'] else 'NO: ' + r['error'][:80]} | {r['seconds']} | {r['chars']} |"
              for name, r in rows]
    with summary.open("a", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    print(f"\nSummary appended to {summary}")


if __name__ == "__main__":
    main()
