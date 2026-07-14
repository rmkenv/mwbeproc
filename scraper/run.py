"""
NYC City Record procurement monitor.

Searches the City Record — both the searchable CROL database and today's print
edition — for procurement notices matching immigration legal services keywords,
scores them, and writes public/data/opportunities.json.

    python scraper/run.py                          # scheduled run
    python scraper/run.py --term "asylum" --dry-run   # ad-hoc search
    python scraper/run.py --days 365 --no-llm      # backfill / market history
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

import cityrecord as CR

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "https://ollama.com")
OLLAMA_MODEL    = os.getenv("OLLAMA_MODEL", "gpt-oss:20b")
OLLAMA_API_KEY  = os.getenv("OLLAMA_API_KEY", "")
NYC_APP_TOKEN   = os.getenv("NYC_APP_TOKEN", "")
FIRM_NAME       = os.getenv("FIRM_NAME", "IQSpatial Legal")
MIN_FIT_SCORE   = int(os.getenv("MIN_FIT_SCORE", "5"))
DAYS_BACK       = int(os.getenv("DAYS_BACK", "45"))
RETAIN_DAYS     = int(os.getenv("RETAIN_DAYS", "180"))

ROOT        = Path(__file__).parent.parent
OUTPUT_PATH = ROOT / "public" / "data" / "opportunities.json"
SEEN_PATH   = Path(__file__).parent / "seen_ids.json"

# Terms sent to CROL's full-text search. Phrases beat single words here — the
# City Record calls this work "Immigration Legal Services" almost verbatim.
SEARCH_TERMS = [
    "immigration legal services",
    "immigration",
    "immigrant",
    "asylum",
    "removal defense",
    "deportation",
    "naturalization",
    "refugee",
    "legal services",
    "legal representation",
    "right to counsel",
    "language access",
    "interpretation services",
    "know your rights",
    "unaccompanied minor",
]
if os.getenv("SEARCH_TERMS"):
    SEARCH_TERMS = [t.strip() for t in os.getenv("SEARCH_TERMS").split(",") if t.strip()]

# Scoring tiers — a hit on "removal defense" is worth far more than one on
# "language access", which shows up in every accessibility boilerplate block.
CORE = ["immigration legal services", "removal defense", "deportation defense",
        "asylum", "immigrant legal", "immigration attorney", "immigration counsel"]
STRONG = ["immigration", "immigrant", "naturalization", "refugee", "asylee",
          "daca", "sijs", "unaccompanied minor", "u visa", "vawa", "tps"]
ADJACENT = ["legal services", "legal aid", "civil legal", "right to counsel",
            "community legal", "know your rights", "language access",
            "interpretation services", "translation services", "newcomer"]

# Boilerplate that appears in nearly every notice's accessibility paragraph.
# Without this, "language access" alone would flag half the City Record.
NOISE_CONTEXT = ["reasonable accommodation", "sign language interpret",
                 "accessibility questions", "language interpretation, or sign language"]


def hits(text: str, keywords: list[str]) -> list[str]:
    """Match on WORD BOUNDARIES, not substrings.

    Naive `if kw in text` is a trap here: "tps" lives inside "https", and every
    City Record notice carries a PASSPort URL. That one substring match scored
    forklifts and police software at 9/10 PURSUE. Same class of bug waits in
    "daca" (Curacao), "vawa", "sijs".
    """
    return [k for k in keywords
            if re.search(rf"\b{re.escape(k)}\b", text, re.IGNORECASE)]


def score(rec: dict) -> tuple[int, list[str]]:
    text = f"{rec.get('title','')} {rec.get('raw_text','')}".lower()

    core     = hits(text, CORE)
    strong   = hits(text, STRONG)
    adjacent = hits(text, ADJACENT)

    # If the ONLY reason this matched is a phrase sitting inside the standard
    # accessibility boilerplate, it's not a lead.
    if not core and not strong and adjacent and any(n in text for n in NOISE_CONTEXT):
        adjacent = [k for k in adjacent if k not in ("language access", "interpretation services")]

    if core:
        s = 9
    elif strong and adjacent:
        s = 8
    elif strong:
        s = 7
    elif adjacent:
        s = 5
    else:
        s = 2

    rt = rec.get("record_type")
    if rt == CR.SOLICITATION:
        s += 1                      # you can bid on this today
    elif rt == CR.INTENT:
        s += 0                      # still contestable
    elif rt == CR.AWARD:
        s -= 2                      # money's spent — this is intel
    else:
        s -= 1

    # An M/WBE noncompetitive small purchase is the most winnable vehicle there is
    # for a certified firm; the agency is explicitly looking for someone like you.
    if rec.get("mwbe_vehicle"):
        s += 1

    # Human services / client services is the category immigration legal work
    # is actually procured under.
    if "human services" in (rec.get("category") or "").lower():
        s += 1

    if closed(rec):
        s -= 3

    return max(1, min(10, s)), core + strong + adjacent


def closed(rec: dict) -> bool:
    if rec.get("record_type") not in (CR.SOLICITATION, CR.INTENT) or not rec.get("due_date"):
        return False
    try:
        return datetime.strptime(rec["due_date"], "%Y-%m-%d").date() < datetime.now().date()
    except ValueError:
        return False


def action_for(s: int, rec: dict) -> str:
    if closed(rec):
        return "CLOSED"
    if rec.get("record_type") == CR.AWARD:
        return "INTEL"
    if s >= 7:
        return "PURSUE"
    if s >= 5:
        return "MONITOR"
    return "SKIP"


SUMMARY_PROMPT = """You are a procurement analyst for {firm}, an MWBE-certified immigration legal services firm.
Summarize this NYC City Record notice in 2-3 plain sentences describing ONLY the scope of work the agency is
buying: what service, for whom, under what vehicle. Do not restate the firm's specialty, do not editorialize
about fit, and do not use the phrase "immigration legal services" unless it appears in the notice itself.
Respond ONLY with JSON, no markdown.

Title: {title}
Agency: {agency}
Notice type: {notice_type}
Selection method: {selection_method}
Category: {category}
Detail: {raw_text}

Return exactly:
{{"summary": "<2-3 sentences>", "certifications_required": [<certifications or eligibility requirements named in the text>]}}
"""


def fallback_summary(rec: dict) -> str:
    kws = ", ".join(rec.get("keyword_matches", [])[:3]) or "keyword match"
    vehicle = f" via {rec['selection_method']}" if rec.get("selection_method") else ""
    return (f"{rec['notice_type']} from {rec['agency']}{vehicle}. "
            f"Matched on: {kws}. Open the notice for full scope and eligibility.")


def enrich(rec: dict) -> dict:
    hdrs = {"Content-Type": "application/json"}
    if OLLAMA_API_KEY:
        hdrs["Authorization"] = f"Bearer {OLLAMA_API_KEY}"
    prompt = SUMMARY_PROMPT.format(firm=FIRM_NAME, **{
        k: rec.get(k, "") for k in
        ("title", "agency", "notice_type", "selection_method", "category", "raw_text")})
    try:
        r = requests.post(f"{OLLAMA_BASE_URL.rstrip('/')}/api/chat", headers=hdrs, timeout=60,
                          json={"model": OLLAMA_MODEL, "stream": False,
                                "messages": [{"role": "user", "content": prompt}]})
        r.raise_for_status()
        c = r.json()["message"]["content"].strip()
        if "</think>" in c:
            c = c.split("</think>")[-1].strip()
        if c.startswith("```"):
            c = c.split("```")[1].removeprefix("json").strip()
        p = json.loads(c)
        return {"summary": p.get("summary") or fallback_summary(rec),
                "certifications_required": p.get("certifications_required") or []}
    except Exception as e:
        log.warning(f"LLM summary failed for '{rec['title'][:50]}': {e}")
        return {"summary": fallback_summary(rec), "certifications_required": []}


def load_seen() -> set:
    try:
        return set(json.loads(SEEN_PATH.read_text()))
    except Exception:
        return set()


def load_existing() -> list[dict]:
    try:
        return json.loads(OUTPUT_PATH.read_text()).get("opportunities", [])
    except Exception:
        return []


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--term", action="append", help="search one term instead of the full list")
    ap.add_argument("--days", type=int, default=DAYS_BACK, help="lookback window")
    ap.add_argument("--no-pdf", action="store_true", help="skip today's print edition")
    ap.add_argument("--no-llm", action="store_true", help="skip Ollama summaries")
    ap.add_argument("--dry-run", action="store_true", help="print, don't write")
    args = ap.parse_args()

    terms = args.term or SEARCH_TERMS
    log.info(f"Searching City Record: {len(terms)} terms, {args.days}-day window")

    records, statuses = [], []

    found, st = CR.search_crol(terms, days_back=args.days, app_token=NYC_APP_TOKEN)
    records += found
    statuses.append(st)
    log.info(f"CROL: {st.found} notices [{'ok' if st.ok else 'FAILED'}] {st.error or st.note}")

    if not args.no_pdf:
        found, st = CR.fetch_todays_pdf(CORE + STRONG + ADJACENT)
        # If the same PIN is already in CROL, the CROL record is richer — keep it.
        crol_pins = {r["pin"] for r in records if r["pin"]}
        found = [f for f in found if f["pin"] not in crol_pins]
        records += found
        statuses.append(st)
        log.info(f"PDF: {len(found)} new [{'ok' if st.ok else 'FAILED'}] {st.error or st.note}")

    seen = load_seen()
    scored = []
    for rec in records:
        fit, matches = score(rec)
        if not matches:
            continue   # $q matched a stray token, not our subject matter
        rec["fit_score"] = fit
        rec["keyword_matches"] = sorted(set(matches))
        rec["action"] = action_for(fit, rec)
        rec["is_open"] = not closed(rec)
        if fit < MIN_FIT_SCORE or rec["action"] == "CLOSED":
            continue
        rec.update({"summary": fallback_summary(rec), "certifications_required": []}
                   if args.no_llm else enrich(rec))
        rec["is_new"] = rec["id"] not in seen
        rec["fetched_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        rec.pop("raw_text", None)
        scored.append(rec)

    log.info(f"{len(scored)} of {len(records)} notices scored >= {MIN_FIT_SCORE}")

    ids = {r["id"] for r in records}
    cutoff = datetime.now(timezone.utc) - timedelta(days=RETAIN_DAYS)
    kept = []
    for o in load_existing():
        if o["id"] in ids or "record_type" not in o:
            continue
        try:
            if datetime.fromisoformat(o.get("fetched_at", "").replace("Z", "+00:00")) > cutoff:
                o["is_new"] = False
                kept.append(o)
        except ValueError:
            pass

    allr = scored + kept
    allr.sort(key=lambda x: (x.get("fit_score", 0), x.get("issue_date", "")), reverse=True)

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "search_terms": terms,
        "window_days": args.days,
        "sources": [s.as_dict() for s in statuses],
        "counts": {
            "total": len(allr),
            "new_this_run": sum(1 for r in scored if r.get("is_new")),
            "solicitations": sum(1 for r in allr if r.get("record_type") == CR.SOLICITATION),
            "intents": sum(1 for r in allr if r.get("record_type") == CR.INTENT),
            "awards": sum(1 for r in allr if r.get("record_type") == CR.AWARD),
            "mwbe": sum(1 for r in allr if r.get("mwbe_vehicle")),
        },
        "opportunities": allr,
    }

    if args.dry_run:
        for r in allr[:25]:
            print(f"{r['fit_score']:>2} {r['action']:<8} {r['notice_type'][:22]:<24} "
                  f"{r['title'][:60]:<62} {r['agency'][:28]}")
        print(f"\n{len(allr)} records ({payload['counts']})")
        return

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(payload, indent=2))
    SEEN_PATH.write_text(json.dumps(sorted(seen | ids), indent=2))
    log.info(f"Wrote {len(allr)} records: {payload['counts']}")

    for s in statuses:
        if not s.ok:
            log.warning(f"SOURCE PROBLEM — {s.name}: {s.error or s.note}")


if __name__ == "__main__":
    main()
