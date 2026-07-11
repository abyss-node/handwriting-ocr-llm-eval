"""Run our parsers on the real printed-Devanagari set from the arXiv stress-test
benchmark (Aditya-PS-05/devanagari-ocr-benchmark) and score with its metrics.

The eval set replicates scripts/make_real.py from that repo exactly: the first 300
train examples of Process-Venue/Sanskrit-OCR-Typed-Dataset whose NFC label is >=3
chars and contains Devanagari.

Usage:
    python bench_real.py build                 # download images + gt.json -> bench/real/
    python bench_real.py run <parser> [-n 50]  # parser: gemini|mistral|reducto|llamaparse
    python bench_real.py score [-n 50]         # chrF++ / CER vs ground truth
"""

import argparse
import base64
import json
import os
import re
import time
import unicodedata
from pathlib import Path

import requests
from dotenv import load_dotenv

HERE = Path(__file__).parent
ROOT = HERE / "bench" / "real"
IMG = ROOT / "images"
OUT = ROOT / "out"
load_dotenv(HERE / ".env")

PROMPT = ("Transcribe the text in this image exactly as written. "
          "Preserve the Devanagari script verbatim. "
          "Output only the transcription, nothing else.")


def build():
    from datasets import load_dataset

    IMG.mkdir(parents=True, exist_ok=True)
    ds = load_dataset("Process-Venue/Sanskrit-OCR-Typed-Dataset", split="train")
    texts, idx = [], 0
    for ex in ds:
        lab = unicodedata.normalize("NFC", ex["label"].strip())
        if len(lab) >= 3 and any("ऀ" <= c <= "ॿ" for c in lab):
            ex["image"].convert("RGB").save(IMG / f"{idx:04d}.png")
            texts.append(lab)
            idx += 1
        if idx >= 300:
            break
    (ROOT / "gt.json").write_text(json.dumps(texts, ensure_ascii=False), encoding="utf-8")
    print(f"built {idx} image/label pairs under {ROOT}")


def parse_gemini(png: Path) -> str:
    model = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash")
    for attempt in range(4):
        r = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
            headers={"x-goog-api-key": os.environ["GEMINI_API_KEY"]},
            json={"contents": [{"parts": [
                {"inline_data": {"mime_type": "image/png",
                                 "data": base64.b64encode(png.read_bytes()).decode()}},
                {"text": PROMPT}]}]},
            timeout=120,
        )
        if r.status_code in (429, 503) and attempt < 3:
            time.sleep(15 * (attempt + 1))
            continue
        r.raise_for_status()
        parts = r.json()["candidates"][0]["content"]["parts"]
        return "".join(p.get("text", "") for p in parts)
    return ""


def parse_mistral(png: Path) -> str:
    for attempt in range(5):
        r = requests.post(
            "https://api.mistral.ai/v1/ocr",
            headers={"Authorization": f"Bearer {os.environ['MISTRAL_API_KEY']}"},
            json={"model": "mistral-ocr-latest",
                  "document": {"type": "image_url",
                               "image_url": "data:image/png;base64,"
                                            + base64.b64encode(png.read_bytes()).decode()}},
            timeout=120,
        )
        if r.status_code == 429 and attempt < 4:
            time.sleep(10 * (attempt + 1))
            continue
        break
    r.raise_for_status()
    time.sleep(1.2)          # stay under free-tier requests/sec
    return "\n".join(p.get("markdown", "") for p in r.json()["pages"])


def parse_reducto(png: Path) -> str:
    headers = {"Authorization": f"Bearer {os.environ['REDUCTO_API_KEY']}"}
    with png.open("rb") as fh:
        up = requests.post("https://platform.reducto.ai/upload", headers=headers,
                           files={"file": (png.name, fh)}, timeout=120)
    up.raise_for_status()
    r = requests.post("https://platform.reducto.ai/parse", headers=headers,
                      json={"input": f"reducto://{up.json()['file_id']}"}, timeout=300)
    r.raise_for_status()
    result = r.json()["result"]
    if result.get("type") == "url":
        result = requests.get(result["url"], timeout=120).json()
    return "\n".join(c.get("content", "") for c in result["chunks"])


def parse_llamaparse(png: Path) -> str:
    from llama_cloud_services import LlamaParse

    parser = LlamaParse(result_type="markdown", premium_mode=True, verbose=False)
    docs = parser.load_data(str(png))
    return "\n".join(d.text for d in docs)


PARSERS = {"gemini": parse_gemini, "mistral": parse_mistral,
           "reducto": parse_reducto, "llamaparse": parse_llamaparse}


def run(parser: str, n: int):
    fn = PARSERS[parser]
    name = parser
    if parser == "gemini":
        model = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash")
        if model != "gemini-3.5-flash":
            name = f"gemini-{model.removeprefix('gemini-')}"
    out_dir = OUT / name
    out_dir.mkdir(parents=True, exist_ok=True)
    done = fails = streak = 0
    for i in range(n):
        out_file = out_dir / f"{i:04d}.txt"
        if out_file.exists():
            continue
        png = IMG / f"{i:04d}.png"
        try:
            text = fn(png)
            out_file.write_text(text, encoding="utf-8")
            done += 1
            streak = 0
        except Exception as e:
            print(f"  {i:04d} FAIL: {str(e)[:120]}", flush=True)
            fails += 1
            streak += 1
            if streak >= 8:
                print(f"{name}: aborting after {streak} consecutive failures "
                      f"(quota likely exhausted; rerun resumes from cache)", flush=True)
                break
        if (i + 1) % 10 == 0:
            print(f"  {name}: {i + 1}/{n}", flush=True)
    print(f"{name}: {done} new, {fails} failed, outputs in {out_dir}")


def clean(s: str, deva_only: bool = False) -> str:
    s = re.sub(r"[#*`_|>~\[\]]", " ", s)          # markdown furniture
    s = unicodedata.normalize("NFC", s)
    if deva_only:                                  # keep Devanagari block + spaces only
        s = "".join(c if ("ऀ" <= c <= "ॿ" or c.isspace()) else " " for c in s)
    return re.sub(r"\s+", " ", s).strip()


def cer(pred: str, ref: str) -> float:
    if not ref:
        return 1.0
    m, n = len(pred), len(ref)
    prev = list(range(n + 1))
    for i in range(1, m + 1):
        cur = [i] + [0] * n
        for j in range(1, n + 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1,
                         prev[j - 1] + (pred[i - 1] != ref[j - 1]))
        prev = cur
    return prev[n] / n


def score(n: int, deva_only: bool = False):
    import sacrebleu

    gt = json.loads((ROOT / "gt.json").read_text(encoding="utf-8"))[:n]
    refs = [clean(t, deva_only) for t in gt]
    mode = "Devanagari-only" if deva_only else "raw"
    print(f"scoring up to {n} items, {mode}; each parser scored on the images it "
          f"completed (paper metrics: chrF++ word_order=2, code-point CER)\n")
    print(f"{'parser':<26}{'n':>5}{'chrF++':>8}{'meanCER':>9}{'medCER':>8}{'cat%':>6}")
    for parser in sorted(OUT.iterdir() if OUT.exists() else []):
        preds, prefs = [], []
        for i in range(n):
            f = parser / f"{i:04d}.txt"
            if f.exists():
                preds.append(clean(f.read_text(encoding="utf-8"), deva_only))
                prefs.append(refs[i])
        if not preds:
            continue
        chrf = sacrebleu.corpus_chrf(preds, [prefs], word_order=2).score
        cers = sorted(cer(p, r) for p, r in zip(preds, prefs))
        mean_cer = sum(cers) / len(cers)
        med_cer = cers[len(cers) // 2]
        cat = 100 * sum(c > 1.0 for c in cers) / len(cers)
        print(f"{parser.name:<26}{len(preds):>5}{chrf:>8.1f}{mean_cer:>9.3f}"
              f"{med_cer:>8.3f}{cat:>6.1f}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("build")
    p_run = sub.add_parser("run")
    p_run.add_argument("parser", choices=PARSERS)
    p_run.add_argument("-n", type=int, default=50)
    p_score = sub.add_parser("score")
    p_score.add_argument("-n", type=int, default=50)
    p_score.add_argument("--deva", action="store_true", help="score Devanagari chars only")
    args = ap.parse_args()
    if args.cmd == "build":
        build()
    elif args.cmd == "run":
        run(args.parser, args.n)
    else:
        score(args.n, args.deva)
