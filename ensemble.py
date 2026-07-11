"""Disagreement-flagging ensemble: two cheap independent parsers on every document,
word-level alignment between them, and a per-document review report.

Design: gemini-3.1-flash-lite is the PRIMARY transcript (better Devanagari, tags
handwriting/stamps/signatures); Mistral OCR is the independent WITNESS. Where they
disagree, neither is trusted — the span is flagged with both readings. Handwriting
tags in the primary are escalation flags regardless of agreement (the cheap tier
misreads cursive even when it tags it correctly; see README).

The ensemble cannot catch errors both parsers agree on (e.g. both misread the same
smudged annotation identically). It converts silent uncertainty into visible flags;
it is not a second ground truth.

Usage:
    python ensemble.py <file1> [file2 ...] [--escalate] [--arbiter gemini|llama] [--merge]

--escalate runs each flagged document through an escalation parse and arbitrates
every disagreement: does the arbiter side with the primary, the witness, or
neither? gemini (full Flash) shares family and prompt with the primary, so its
verdicts are corroboration; llama (LlamaParse premium) is an independent family,
a genuine third witness.

--merge composes results/<doc>/final-transcript.md: every disagreement is put to
a vote across all available readings (primary, witness, and each cached arbiter).
A reading with >=3 votes is adopted silently; a unique 2-vote plurality is adopted
with an inline flag listing alternates; anything else becomes an inline
[ensemble-review: ...] tag carrying every reading — the fan-out fields where four
parsers give four readings are exactly the ones no model can settle.

Consumes cached parses from results/<doc>/ when present (gemini-3.1-flash-lite.md,
mistral-ocr.md, gemini.md); calls the APIs (keys in .env) only for what is missing.
Writes results/<doc>/ensemble-report.md and prints a summary table.
"""

import argparse
import difflib
import os
import re
import sys
import unicodedata
from pathlib import Path

HERE = Path(__file__).parent
RESULTS = HERE / "results"

PRIMARY = "gemini-3.1-flash-lite.md"
WITNESS = "mistral-ocr.md"
# arbiters: parse-file candidates in priority order. gemini = full Flash (503/quota
# preview fallback), same family+prompt as the primary -> corroboration only.
# llama = LlamaParse premium (prompted variant first: same accuracy, speaks our tag
# convention), independent family -> genuine third witness.
ARBITERS = {
    "gemini": [("gemini-3.5-flash", "gemini.md"),
               ("gemini-3-flash-preview", "gemini-3-flash-preview.md")],
    "llama": [("llamaparse-prompted", "llamaparse-prompted.md"),
              ("llamaparse-premium", "llamaparse-premium.md")],
}

TAG_RE = re.compile(r"\[(handwriting|stamp|signature|crossed out text)\s*:\s*([^\[\]]*)\]",
                    re.IGNORECASE)
AGREEMENT_REVIEW_THRESHOLD = 0.80
EDGE_PUNCT = ".,;:()—–-/'\"!?"


def ensure_parses(doc: Path, out_dir: Path):
    import compare  # reuse the harness parsers + retry logic

    if not (out_dir / PRIMARY).exists():
        os.environ["GEMINI_MODEL"] = "gemini-3.1-flash-lite"
        r = compare.run_gemini(doc, out_dir)
        if not r["ok"]:
            sys.exit(f"{doc.name}: primary parse failed: {r['error']}")
    if not (out_dir / WITNESS).exists():
        r = compare.run_mistral(doc, out_dir)
        if not r["ok"]:
            sys.exit(f"{doc.name}: witness parse failed: {r['error']}")


HW_OPEN, HW_CLOSE = "", ""        # private-use sentinels, never in parses


def tokens(text: str, with_mask: bool = False):
    """Normalize to comparable word tokens: strip tag wrappers (keep their content),
    markdown furniture, and HTML; NFC-normalize; split on whitespace; collapse
    letter-spaced runs (H E A D I N G -> HEADING). With with_mask=True also returns
    a parallel bool list marking tokens that came from inside a tag region
    (handwriting/stamp/signature/crossed-out) — auto-adoption is unsafe there."""
    prev = None
    while prev != text:                       # peel nested tags until stable
        prev = text
        text = TAG_RE.sub(lambda m: HW_OPEN + m.group(2) + HW_CLOSE, text)
    text = re.sub(r"<[^>\n]{1,80}>", " ", text)
    text = re.sub(r"[#*`_|>~\[\]•]", " ", text)
    text = unicodedata.normalize("NFC", text)
    toks, mask, depth = [], [], 0
    for t in re.split(r"\s+", text):
        depth += t.count(HW_OPEN)
        inside = depth > 0
        depth -= t.count(HW_CLOSE)
        t = t.replace(HW_OPEN, "").replace(HW_CLOSE, "")
        if t.strip(EDGE_PUNCT):
            toks.append(t)
            mask.append(inside)
    toks, mask = collapse_spaced(toks, mask)
    return (toks, mask) if with_mask else toks


def collapse_spaced(toks: list, mask: list) -> tuple:
    """Merge runs of >=3 consecutive single-alphanumeric-character tokens into one
    token: letter-spaced headings tokenize as noise otherwise. Runs of 1-2 pass
    through (standalone initials in signatures are real tokens)."""
    out, om, run, rm = [], [], [], []
    for t, m in zip(toks, mask):
        if len(t) == 1 and t.isalnum():
            run.append(t)
            rm.append(m)
            continue
        if len(run) >= 3:
            out.append("".join(run)), om.append(any(rm))
        else:
            out.extend(run), om.extend(rm)
        run, rm = [], []
        out.append(t)
        om.append(m)
    if len(run) >= 3:
        out.append("".join(run)), om.append(any(rm))
    else:
        out.extend(run), om.extend(rm)
    return out, om


def norm(tok: str) -> str:
    """Comparison key: case- and edge-punctuation-insensitive. NAME: vs NAME,
    Co, vs Co. and Of vs OF are formatting noise, not disagreement. Interior
    punctuation is preserved (2/3 vs 23 is a real disagreement). Reports always
    show the raw readings; only alignment uses these keys."""
    return tok.strip(EDGE_PUNCT).casefold() or tok.casefold()


def context(toks: list, lo: int, hi: int, width: int = 4) -> str:
    pre = " ".join(toks[max(0, lo - width):lo])
    span = " ".join(toks[lo:hi]) or "∅"
    return pre, span


def ensure_escalation(doc: Path, out_dir: Path, arbiter: str) -> Path:
    candidates = ARBITERS[arbiter]
    for _, fname in candidates:
        if (out_dir / fname).exists():
            return out_dir / fname
    import compare
    for model, fname in candidates:
        if arbiter == "llama":
            r = compare.run_llamaparse(doc, out_dir, premium=True,
                                       prompted=(model == "llamaparse-prompted"))
        else:
            os.environ["GEMINI_MODEL"] = model
            r = compare.run_gemini(doc, out_dir)
        if r["ok"]:
            return out_dir / fname
        print(f"  escalation via {model} failed ({r['error'][:80]}), trying fallback")
    sys.exit(f"{doc.name}: escalation parse failed on all models")


def arbitrate(esc_raw: str, res: dict):
    """For each flagged disagreement, read what the escalated parse has at that
    position and record which cheap reading it reproduces. Positions come from ONE
    global alignment of the escalated parse against the primary (equal blocks map
    primary token indices to escalated indices) — local context search is fragile
    on multi-letter files where near-identical boilerplate repeats."""
    esc_toks = tokens(esc_raw)
    esc_keys = [norm(t) for t in esc_toks]
    p_keys = res["p_keys"]

    p2e = {}
    for op, a_lo, a_hi, b_lo, b_hi in difflib.SequenceMatcher(
            a=p_keys, b=esc_keys, autojunk=False).get_opcodes():
        if op == "equal":
            for k in range(a_hi - a_lo):
                p2e[a_lo + k] = b_lo + k

    for d in res["disagreements"]:
        a_lo, a_hi = d["a_lo"], d["a_hi"]
        left = next((p2e[j] for j in range(a_lo - 1, max(-1, a_lo - 40), -1) if j in p2e), None)
        right = next((p2e[j] for j in range(a_hi, min(len(p_keys), a_hi + 40)) if j in p2e), None)
        lo = left + 1 if left is not None else 0
        hi = right if right is not None else len(esc_keys)
        if (left is None and right is None) or lo > hi:
            d["verdict"], d["esc"] = "unaligned", "—"
            continue
        seg = esc_keys[lo:hi]
        p_span, w_span = d["p_keys"], d["w_keys"]
        if seg == p_span:
            verdict = "primary"
        elif seg == w_span:
            verdict = "witness"
        elif not seg and not p_span:
            verdict = "primary"
        elif not seg and not w_span:
            verdict = "witness"
        else:
            verdict = "neither"
        d["verdict"] = verdict
        d["esc"] = " ".join(esc_toks[lo:hi]) or "∅"

    p_keys = res["p_keys"]
    w_keys = res["w_keys"]
    res["esc_vs_primary"] = difflib.SequenceMatcher(a=esc_keys, b=p_keys, autojunk=False).ratio()
    res["esc_vs_witness"] = difflib.SequenceMatcher(a=esc_keys, b=w_keys, autojunk=False).ratio()
    res["verdict_counts"] = {v: sum(1 for d in res["disagreements"] if d.get("verdict") == v)
                             for v in ("primary", "witness", "neither", "unaligned")}


def analyze(doc: Path, out_dir: Path) -> dict:
    primary_raw = (out_dir / PRIMARY).read_text(encoding="utf-8")
    witness_raw = (out_dir / WITNESS).read_text(encoding="utf-8")

    hw_tags = [m.group(0) for m in TAG_RE.finditer(primary_raw)
               if m.group(1).lower() == "handwriting"]

    p_toks, p_mask = tokens(primary_raw, with_mask=True)
    w_toks = tokens(witness_raw)
    p_keys, w_keys = [norm(t) for t in p_toks], [norm(t) for t in w_toks]
    sm = difflib.SequenceMatcher(a=p_keys, b=w_keys, autojunk=False)
    agreement = sm.ratio()

    disagreements = []
    for op, a_lo, a_hi, b_lo, b_hi in sm.get_opcodes():
        if op == "equal":
            continue
        if " ".join(p_keys[a_lo:a_hi]) == " ".join(w_keys[b_lo:b_hi]):
            continue                          # same words, different token boundaries
        pre, p_span = context(p_toks, a_lo, a_hi)
        _, w_span = context(w_toks, b_lo, b_hi)
        hw = any(p_mask[max(0, a_lo - 1):a_hi + 1])   # widened so insertions inherit
        disagreements.append({"after": pre, "primary": p_span, "witness": w_span,
                              "a_lo": a_lo, "a_hi": a_hi, "hw": hw,
                              "p_keys": p_keys[a_lo:a_hi], "w_keys": w_keys[b_lo:b_hi]})

    escalate = bool(hw_tags) or agreement < AGREEMENT_REVIEW_THRESHOLD
    reasons = []
    if hw_tags:
        reasons.append(f"{len(hw_tags)} handwriting region(s) tagged by primary")
    if agreement < AGREEMENT_REVIEW_THRESHOLD:
        reasons.append(f"agreement {agreement:.0%} below {AGREEMENT_REVIEW_THRESHOLD:.0%}")

    return {"doc": doc.name, "agreement": agreement, "disagreements": disagreements,
            "hw_tags": hw_tags, "escalate": escalate, "reasons": reasons,
            "p_keys": p_keys, "w_keys": w_keys}


PARSER_LABEL = {"gemini": "flash", "llama": "lp-premium"}


def resolve(d: dict, arbiters: list) -> tuple:
    """Vote across all readings of one disagreement. Returns (kind, replacement,
    votes) where kind is auto / plurality / review."""
    votes = {}   # normalized reading -> {"display": raw, "voters": [labels]}

    def cast(key, display, who):
        v = votes.setdefault(key, {"display": display, "voters": []})
        v["voters"].append(who)

    cast(" ".join(d["p_keys"]), d["primary"], "flash-lite")
    cast(" ".join(d["w_keys"]), d["witness"], "mistral")
    for arb in arbiters:
        a = d["arb"][arb]
        if a["verdict"] == "primary":
            cast(" ".join(d["p_keys"]), d["primary"], PARSER_LABEL[arb])
        elif a["verdict"] == "witness":
            cast(" ".join(d["w_keys"]), d["witness"], PARSER_LABEL[arb])
        elif a["verdict"] == "neither":
            toks = [] if a["esc"] in ("∅", "—") else a["esc"].split()
            cast(" ".join(norm(t) for t in toks), a["esc"] if toks else "∅", PARSER_LABEL[arb])
        # unaligned casts no vote

    ranked = sorted(votes.values(), key=lambda v: -len(v["voters"]))
    best, n = ranked[0], len(ranked[0]["voters"])
    tied = sum(1 for v in ranked if len(v["voters"]) == n)
    text = best["display"] if best["display"] != "∅" else ""
    total = sum(len(v["voters"]) for v in ranked)
    hw = d.get("hw", False)
    # human-validated policy (2026-07-11): handwriting never adopts silently — a
    # cross-family 2-of-4 plurality on a handwritten date was WRONG, and 3-parser
    # consensus on a smudged section number was wrong too (both scripts, shared
    # language prior). Typed text keeps the vote tiers.
    if n >= 3 and tied == 1:
        if hw:
            return "auto_hw", f"{text} [ensemble {n}-of-{total}, handwriting]".strip(), votes
        return "auto", text, votes
    if n == 2 and tied == 1 and not hw:
        alts = " / ".join(v["display"] for v in ranked[1:])
        return "plurality", f"{text} [ensemble {n}-of-{total}; alts: {alts}]".strip(), votes
    label = "ensemble-review, handwriting" if hw else "ensemble-review"
    readings = " | ".join(f"{v['display']} ({'+'.join(v['voters'])})" for v in ranked)
    return "review", f"[{label}: {readings}]", votes


def rebuild(lo: int, hi: int, toks: list, subs: list) -> str:
    out, i = [], lo
    for a, b, rep in subs:
        if a < lo or b > hi:
            continue
        out += toks[i:a]
        if rep:
            out.append(rep)
        i = b
    out += toks[i:hi]
    return " ".join(out)


def write_transcript(primary_raw: str, res: dict, out_dir: Path, arbiters: list) -> dict:
    """Compose final-transcript.md: primary text with each disagreement span replaced
    by its voted resolution. Untouched lines keep the primary's raw formatting;
    lines a substitution touches are rebuilt from tokens (markdown furniture lost)."""
    counts = {"auto": 0, "auto_hw": 0, "plurality": 0, "review": 0}
    subs = []
    for d in res["disagreements"]:
        kind, rep, _ = resolve(d, arbiters)
        counts[kind] += 1
        subs.append((d["a_lo"], d["a_hi"], rep))
    subs.sort()

    lines = primary_raw.splitlines()
    line_toks = [tokens(l) for l in lines]
    flat = [t for lt in line_toks for t in lt]
    p_toks = tokens(primary_raw)

    body = []
    if flat != p_toks:      # per-line tokenization drifted from the global stream
        body = [rebuild(0, len(p_toks), p_toks, subs),
                "", "*(line structure lost: per-line tokenization drifted; "
                "transcript emitted as a single stream)*"]
    else:
        ranges, g = [], 0
        for lt in line_toks:
            ranges.append((g, g + len(lt)))
            g += len(lt)
        changed = set()
        for a, b, _ in subs:
            for li, (ls, le) in enumerate(ranges):
                if (a < le and b > ls) or (a == b and ls <= a < le):
                    changed.add(li)
            if a == b == len(flat) and lines:          # insertion at document end
                changed.add(len(lines) - 1)
        li = 0
        while li < len(lines):
            if li not in changed:
                body.append(lines[li])
                li += 1
                continue
            lo = ranges[li][0]
            while li in changed:                        # merge consecutive changed lines
                hi = ranges[li][1]
                li += 1
            body.append(rebuild(lo, hi, p_toks, subs))

    votes_per = 2 + len(arbiters)
    header = [
        f"# Final transcript — {res['doc']}",
        "",
        f"Composed from the flash-lite primary; {len(subs)} disagreement(s) resolved by "
        f"vote across {votes_per} readings (primary, witness"
        + "".join(f", {PARSER_LABEL[a]}" for a in arbiters) + "):",
        f"**{counts['auto']} auto (typed, ≥3 votes) · {counts['auto_hw']} handwriting "
        f"≥3-vote (adopted, flagged) · {counts['plurality']} plurality (typed, 2 votes, "
        f"flagged) · {counts['review']} review (no consensus, or any handwriting "
        "plurality — handwriting never adopts silently)**.",
        "Not ground truth: plurality and review markers need human eyes, and "
        "agreed-upon errors carry no marker at all.",
        "", "---", "",
    ]
    (out_dir / "final-transcript.md").write_text("\n".join(header + body), encoding="utf-8")
    return counts


def write_report(res: dict, out_dir: Path, report_name: str = "ensemble-report.md"):
    lines = [
        f"# Ensemble report — {res['doc']}",
        "",
        f"Primary: `{PRIMARY}` · Witness: `{WITNESS}` · "
        "alignment ignores case/edge-punctuation/letter-spacing; readings shown raw",
        f"**Agreement: {res['agreement']:.1%}** · "
        f"**Escalate: {'YES — ' + '; '.join(res['reasons']) if res['escalate'] else 'no'}**",
        "",
    ]
    if res["hw_tags"]:
        lines += ["## Handwriting regions (escalation flags)", ""]
        lines += [f"- `{t}`" for t in res["hw_tags"]]
        lines.append("")
    arbitrated = "verdict_counts" in res
    if res["disagreements"]:
        if arbitrated:
            lines += ["## Disagreements — arbitrated by escalation tier", "",
                      f"Escalation parse: `{res['esc_file']}` · "
                      f"esc↔primary {res['esc_vs_primary']:.1%} · "
                      f"esc↔witness {res['esc_vs_witness']:.1%}",
                      "",
                      "| after … | primary (flash-lite) | witness (mistral) | escalated reading | sided with |",
                      "|---|---|---|---|---|"]
            lines += [f"| …{d['after']} | {d['primary']} | {d['witness']} | "
                      f"{d['esc']} | {d['verdict'].upper()} |"
                      for d in res["disagreements"]]
            c = res["verdict_counts"]
            independence = (
                "The arbiter is an independent family (LlamaParse), so verdicts are "
                "genuine third-witness adjudication; 2-of-3 readings can be adopted."
                if "llama" in res["esc_file"] else
                "Primary and the escalation model share family and prompt — "
                "'sided with primary' is corroboration, not independent adjudication.")
            lines += ["",
                      f"**Arbitration: {c['primary']} primary · {c['witness']} witness · "
                      f"{c['neither']} neither · {c['unaligned']} unaligned.** "
                      f"{independence} NEITHER rows are where the arbiter added a "
                      "third reading.", ""]
        else:
            lines += ["## Disagreements (neither reading trusted)", "",
                      "| after … | primary (flash-lite) | witness (mistral) |",
                      "|---|---|---|"]
            lines += [f"| …{d['after']} | {d['primary']} | {d['witness']} |"
                      for d in res["disagreements"]]
            lines.append("")
    else:
        lines += ["No token-level disagreements.", ""]
    lines += ["*Agreed-upon text can still be wrong — agreement measures independence-",
              "weighted confidence, not truth. Escalated pages go to full Gemini Flash",
              "or LlamaParse premium.*"]
    (out_dir / report_name).write_text("\n".join(lines), encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    ap.add_argument("--escalate", action="store_true",
                    help="run flagged docs through the escalation tier and arbitrate disagreements")
    ap.add_argument("--arbiter", choices=sorted(ARBITERS), default="gemini",
                    help="escalation parser: gemini (same family as primary, corroboration) "
                         "or llama (LlamaParse premium, independent third witness)")
    ap.add_argument("--merge", action="store_true",
                    help="vote across all available readings and compose "
                         "results/<doc>/final-transcript.md (implies --escalate; uses "
                         "every arbiter with a cached parse)")
    args = ap.parse_args()
    if args.merge:
        args.escalate = True

    print(f"{'document':<14}{'agreement':>10}{'flags':>7}  verdict")
    for f in args.files:
        doc = Path(f).resolve()
        if not doc.exists():
            print(f"{doc.name:<14}  SKIP (not found)")
            continue
        out_dir = RESULTS / doc.stem
        out_dir.mkdir(parents=True, exist_ok=True)
        ensure_parses(doc, out_dir)
        res = analyze(doc, out_dir)
        merge_counts = None
        if args.escalate and res["escalate"]:
            if args.merge:
                # arbitrate with every arbiter that has (or can get) a parse;
                # args.arbiter last so the written report reflects it
                order = [a for a in ARBITERS if a != args.arbiter] + [args.arbiter]
                arbiters_used = []
                for arb in order:
                    cached = next((out_dir / f for _, f in ARBITERS[arb]
                                   if (out_dir / f).exists()), None)
                    if cached is None and arb != args.arbiter:
                        continue        # only the chosen arbiter is worth an API call
                    esc_path = cached or ensure_escalation(doc, out_dir, arb)
                    res["esc_file"] = esc_path.name
                    arbitrate(esc_path.read_text(encoding="utf-8"), res)
                    for d in res["disagreements"]:
                        d.setdefault("arb", {})[arb] = {"verdict": d["verdict"],
                                                        "esc": d["esc"]}
                    arbiters_used.append(arb)
                primary_raw = (out_dir / PRIMARY).read_text(encoding="utf-8")
                merge_counts = write_transcript(primary_raw, res, out_dir,
                                                sorted(arbiters_used))
            else:
                esc_path = ensure_escalation(doc, out_dir, args.arbiter)
                res["esc_file"] = esc_path.name
                arbitrate(esc_path.read_text(encoding="utf-8"), res)
        elif args.merge:
            # accepted at cheap tier: final transcript is the primary, verbatim
            primary_raw = (out_dir / PRIMARY).read_text(encoding="utf-8")
            (out_dir / "final-transcript.md").write_text(
                f"# Final transcript — {res['doc']}\n\n"
                "Accepted at cheap tier (no escalation flags); flash-lite primary "
                "verbatim.\n\n---\n\n" + primary_raw, encoding="utf-8")
            merge_counts = {"auto": 0, "auto_hw": 0, "plurality": 0, "review": 0}
        report_name = ("ensemble-report.md" if args.arbiter == "gemini"
                       else f"ensemble-report-{args.arbiter}.md")
        write_report(res, out_dir, report_name)
        verdict = "ESCALATE — " + "; ".join(res["reasons"]) if res["escalate"] else "accept cheap tier"
        print(f"{res['doc']:<14}{res['agreement']:>9.1%}{len(res['disagreements']):>7}  {verdict}")
        if merge_counts is not None:
            print(f"{'':<14}  merge: {merge_counts['auto']} auto / "
                  f"{merge_counts['auto_hw']} hw-flagged / "
                  f"{merge_counts['plurality']} plurality / {merge_counts['review']} review "
                  f"-> final-transcript.md")
        if "verdict_counts" in res:
            c = res["verdict_counts"]
            print(f"{'':<14}  arbitration: {c['primary']} primary / {c['witness']} witness / "
                  f"{c['neither']} neither / {c['unaligned']} unaligned; "
                  f"esc-vs-primary {res['esc_vs_primary']:.0%}, esc-vs-witness {res['esc_vs_witness']:.0%}")
    out_name = ("ensemble-report.md" if args.arbiter == "gemini"
                else f"ensemble-report-{args.arbiter}.md")
    print(f"\nreports written to results/<doc>/{out_name}")


if __name__ == "__main__":
    main()
