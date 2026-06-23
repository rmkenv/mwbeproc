"""
MWBE Procurement Monitor — scraper entry point.
Sources:
  - NYC City Record RSS feed (reliable, no API key)
  - SAM.gov REST API (federal opportunities, free)
  - NYS Contract Reporter (form POST)
  - Nassau / Suffolk county page scrapes
Triggered by GitHub Actions Mon/Thu at 7am ET.
"""

import json
import os
import uuid
import logging
from datetime import datetime, timedelta
from pathlib import Path

import requests
from bs4 import BeautifulSoup

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
OLLAMA_MODEL    = os.getenv("OLLAMA_MODEL", "qwen3.5:9b")
OLLAMA_API_KEY  = os.getenv("OLLAMA_API_KEY", "")
FIRM_NAME       = os.getenv("FIRM_NAME", "IQSpatial Legal")
MIN_FIT_SCORE   = int(os.getenv("MIN_FIT_SCORE", "5"))
SAM_API_KEY     = os.getenv("SAM_API_KEY", "")   # optional — free at sam.gov/api
DAYS_BACK       = 30

OUTPUT_PATH = Path(__file__).parent.parent / "public" / "data" / "opportunities.json"
SEEN_PATH   = Path(__file__).parent / "seen_ids.json"

KEYWORDS = [
    "immigration", "immigrant", "legal services", "legal aid",
    "asylum", "removal defense", "naturalization", "DACA",
    "refugee", "community legal", "SIJS", "TPS", "humanitarian",
    "know your rights", "U visa", "VAWA", "language access",
]

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; MWBEMonitor/1.0; +https://iqspatial.com)"}

# ── Source 1: NYC City Record Online (Open Data dataset dg92-zbpx) ────────────

def fetch_nyc_city_record() -> list[dict]:
    """
    NYC City Record Online via Open Data dataset dg92-zbpx.
    NOTE: Cannot mix $q and $where on this dataset — use $q only.
    """
    results  = []
    seen_ids = set()

    for keyword in KEYWORDS:
        try:
            r = requests.get(
                "https://data.cityofnewyork.us/resource/dg92-zbpx.json",
                params={
                    "$q": keyword,
                    "$limit": 50,
                },
                timeout=20,
                headers=HEADERS,
            )
            r.raise_for_status()
            for c in r.json():
                record_id = c.get("record_id", c.get("id", uuid.uuid4().hex[:8]))
                uid = f"CROL-{record_id}"
                if uid in seen_ids:
                    continue
                seen_ids.add(uid)
                results.append({
                    "id": uid,
                    "title": c.get("title", c.get("notice_title", "Unknown")),
                    "agency": c.get("agency_name", c.get("agency", "")),
                    "jurisdiction": "NYC",
                    "source": "NYC City Record Online",
                    "source_url": f"https://a856-cityrecord.nyc.gov/Section/Details/{record_id}" if record_id else "https://a856-cityrecord.nyc.gov/Section",
                    "amount": 0,
                    "due_date": c.get("due_date", c.get("response_date", "")),
                    "issue_date": c.get("published_date", ""),
                    "contract_type": c.get("notice_type", c.get("type", "Solicitation")),
                    "keyword_match": keyword,
                    "raw_text": f"{c.get('title','')} {c.get('notice_title','')} {c.get('agency_name','')} {c.get('description','')}",
                })
        except Exception as e:
            log.warning(f"City Record Online failed for '{keyword}': {e}")

    log.info(f"NYC City Record Online: {len(results)} keyword-matched items")
    return results


# ── Source 2: SAM.gov (federal) ───────────────────────────────────────────────

def fetch_sam_gov(keyword: str) -> list[dict]:
    """
    SAM.gov Opportunities API.
    Correct production URL: https://api.sam.gov/prod/opportunities/v2/search
    Requires free API key from sam.gov — add SAM_API_KEY secret.
    Uses 'title' param (not 'keywords') for text search.
    """
    if not SAM_API_KEY:
        return []   # Skip entirely without a key — endpoint rejects keyless requests

    results = []
    posted_from = (datetime.now() - timedelta(days=DAYS_BACK)).strftime("%m/%d/%Y")

    params = {
        "api_key": SAM_API_KEY,
        "title": keyword,
        "postedFrom": posted_from,
        "postedTo": datetime.now().strftime("%m/%d/%Y"),
        "ptype": "o,p,k,r",
        "limit": 25,
        "offset": 0,
    }

    try:
        r = requests.get(
            "https://api.sam.gov/prod/opportunities/v2/search",
            params=params,
            timeout=20,
            headers=HEADERS,
        )
        r.raise_for_status()
        data = r.json()

        for opp in data.get("opportunitiesData", []):
            opp_id = opp.get("noticeId", uuid.uuid4().hex[:8])
            results.append({
                "id": f"SAM-{opp_id}",
                "title": opp.get("title", "Unknown"),
                "agency": opp.get("fullParentPathName", opp.get("organizationName", "")),
                "jurisdiction": "Federal",
                "source": "SAM.gov",
                "source_url": f"https://sam.gov/opp/{opp_id}/view",
                "amount": 0,
                "due_date": opp.get("responseDeadLine", ""),
                "issue_date": opp.get("postedDate", ""),
                "contract_type": opp.get("type", "Solicitation"),
                "keyword_match": keyword,
                "raw_text": f"{opp.get('title','')} {opp.get('description','')} {opp.get('organizationName','')}",
            })
    except Exception as e:
        log.warning(f"SAM.gov failed for '{keyword}': {e}")

    return results


# ── Source 3: NYS Contract Reporter ──────────────────────────────────────────

def fetch_nys_contract_reporter(keyword: str) -> list[dict]:
    """NYS Contract Reporter via form POST — working in prior runs."""
    session = requests.Session()
    session.headers.update(HEADERS)
    try:
        session.get("https://www.nyscr.ny.gov/oppSrchForm.cfm", timeout=10)
        start = (datetime.now() - timedelta(days=DAYS_BACK)).strftime("%m/%d/%Y")
        end   = datetime.now().strftime("%m/%d/%Y")
        resp  = session.post(
            "https://www.nyscr.ny.gov/oppList.cfm",
            data={"oppType": "ALL", "keyword": keyword, "dateFrom": start, "dateTo": end, "submit": "Search"},
            timeout=20,
        )
        soup    = BeautifulSoup(resp.text, "html.parser")
        results = []
        for row in soup.select("table.resultsTable tr:not(:first-child)"):
            cols = row.find_all("td")
            if len(cols) < 5:
                continue
            link  = cols[1].find("a")
            title = link.get_text(strip=True) if link else cols[1].get_text(strip=True)
            href  = f"https://www.nyscr.ny.gov/{link['href']}" if link and link.get("href") else "https://www.nyscr.ny.gov"
            results.append({
                "id": f"NYSCR-{cols[0].get_text(strip=True)}",
                "title": title,
                "agency": cols[2].get_text(strip=True),
                "jurisdiction": "NYS",
                "source": "NYS Contract Reporter",
                "source_url": href,
                "amount": 0,
                "due_date": cols[4].get_text(strip=True),
                "issue_date": "",
                "contract_type": cols[3].get_text(strip=True) or "RFP",
                "keyword_match": keyword,
                "raw_text": f"{title} {cols[2].get_text(strip=True)}",
            })
        return results
    except Exception as e:
        log.warning(f"NYS CR failed for '{keyword}': {e}")
        return []


# ── Source 4: Nassau County ───────────────────────────────────────────────────

def fetch_nassau(keyword: str) -> list[dict]:
    try:
        r    = requests.get("https://www.nassaucountyny.gov/1085/Procurement", timeout=15, headers=HEADERS)
        soup = BeautifulSoup(r.text, "html.parser")
        results = []
        for link in soup.find_all("a", string=lambda t: t and keyword.lower() in t.lower()):
            href = link.get("href", "")
            if not href.startswith("http"):
                href = "https://www.nassaucountyny.gov" + href
            results.append({
                "id": f"NASSAU-{uuid.uuid4().hex[:6]}",
                "title": link.get_text(strip=True),
                "agency": "Nassau County",
                "jurisdiction": "Nassau",
                "source": "Nassau County Portal",
                "source_url": href or "https://www.nassaucountyny.gov/1085/Procurement",
                "amount": 0,
                "due_date": "",
                "issue_date": "",
                "contract_type": "Bid",
                "keyword_match": keyword,
                "raw_text": link.get_text(strip=True),
            })
        return results
    except Exception as e:
        log.warning(f"Nassau scrape failed for '{keyword}': {e}")
        return []


# ── Source 5: Suffolk County ──────────────────────────────────────────────────

def fetch_suffolk(keyword: str) -> list[dict]:
    try:
        r    = requests.get(
            "https://www.suffolkcountyny.gov/Departments/County-Executive/Procurement",
            timeout=15, headers=HEADERS,
        )
        soup = BeautifulSoup(r.text, "html.parser")
        results = []
        for link in soup.find_all("a", string=lambda t: t and keyword.lower() in t.lower()):
            href = link.get("href", "")
            if not href.startswith("http"):
                href = "https://www.suffolkcountyny.gov" + href
            results.append({
                "id": f"SUFFOLK-{uuid.uuid4().hex[:6]}",
                "title": link.get_text(strip=True),
                "agency": "Suffolk County",
                "jurisdiction": "Suffolk",
                "source": "Suffolk County Portal",
                "source_url": href or "https://www.suffolkcountyny.gov",
                "amount": 0,
                "due_date": "",
                "issue_date": "",
                "contract_type": "Bid",
                "keyword_match": keyword,
                "raw_text": link.get_text(strip=True),
            })
        return results
    except Exception as e:
        log.warning(f"Suffolk scrape failed for '{keyword}': {e}")
        return []


# ── Deduplication ─────────────────────────────────────────────────────────────

def load_seen() -> set:
    if SEEN_PATH.exists():
        return set(json.loads(SEEN_PATH.read_text()))
    return set()

def save_seen(seen: set):
    SEEN_PATH.write_text(json.dumps(sorted(seen), indent=2))


# ── LLM scoring ───────────────────────────────────────────────────────────────

SCORE_PROMPT = """You are a procurement analyst for {firm}, an MWBE-certified immigration legal services firm.
Evaluate this government opportunity and respond ONLY with a JSON object — no markdown, no preamble.

Opportunity:
Title: {title}
Agency: {agency}
Jurisdiction: {jurisdiction}
Type: {contract_type}
Raw text: {raw_text}

Return exactly:
{{
  "fit_score": <integer 1-10>,
  "action": "<PURSUE|MONITOR|SKIP>",
  "summary": "<2-3 sentence plain-English description of scope and fit>",
  "keyword_matches": [<list of matching keywords from the text>],
  "certifications_required": [<list of certifications or eligibility requirements mentioned>]
}}

Scoring guide:
9-10: Direct immigration legal services RFP, MWBE preferred/required
7-8: Strong legal services fit, immigration adjacent
5-6: Partial fit — legal services component or referral opportunity
1-4: Weak match, monitor only
"""

def score_opportunity(opp: dict) -> dict | None:
    # Prefix with /no_think to disable Qwen3.5 thinking mode — keeps output clean JSON
    prompt = "/no_think\n\n" + SCORE_PROMPT.format(firm=FIRM_NAME, **opp)
    base = OLLAMA_BASE_URL.rstrip("/")
    chat_url = f"{base}/api/chat" if not base.endswith("/api") else f"{base}/chat"
    log.info(f"Scoring '{opp['title'][:50]}' via {chat_url}")
    try:
        hdrs = {"Content-Type": "application/json"}
        if OLLAMA_API_KEY:
            hdrs["Authorization"] = f"Bearer {OLLAMA_API_KEY}"
        r = requests.post(
            chat_url,
            json={"model": OLLAMA_MODEL, "messages": [{"role": "user", "content": prompt}], "stream": False},
            headers=hdrs,
            timeout=60,
        )
        r.raise_for_status()
        content = r.json()["message"]["content"].strip()
        # Strip <think>...</think> blocks if present
        if "<think>" in content:
            content = content.split("</think>")[-1].strip()
        # Strip markdown fences
        if content.startswith("```"):
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]
        return {**opp, **json.loads(content.strip())}
    except Exception as e:
        log.warning(f"LLM scoring failed for '{opp['title']}': {e}")
        # Keyword fallback
        text  = opp.get("raw_text", "").lower()
        score = min(sum(3 for k in ["immigration", "legal services", "removal defense", "asylum"] if k in text), 10)
        score = max(score, 1)
        return {
            **opp,
            "fit_score": score,
            "action": "PURSUE" if score >= 7 else "MONITOR" if score >= 5 else "SKIP",
            "summary": f"{opp['title']} from {opp['agency']}. Keyword: '{opp['keyword_match']}'.",
            "keyword_matches": [opp["keyword_match"]],
            "certifications_required": [],
        }


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    log.info("Starting MWBE procurement scrape run")
    seen = load_seen()
    raw: list[dict] = []

    # NYC City Record Online — Procurement section
    log.info("Fetching NYC City Record Online...")
    raw += fetch_nyc_city_record()

    # Keyword-based sources
    for kw in KEYWORDS:
        log.info(f"Fetching keyword: {kw}")
        raw += fetch_sam_gov(kw)
        raw += fetch_nys_contract_reporter(kw)
        raw += fetch_nassau(kw)
        raw += fetch_suffolk(kw)

    # Deduplicate
    unique = {}
    for o in raw:
        # Skip records with no meaningful title
        title = o.get("title", "").strip()
        if not title or title in ("Unknown Award", "Unknown Solicitation", "Unknown"):
            continue
        if o["id"] not in seen and o["id"] not in unique:
            unique[o["id"]] = o
    log.info(f"Found {len(unique)} new unique opportunities (with titles)")

    # Score
    scored = []
    for opp in unique.values():
        result = score_opportunity(opp)
        if result and result.get("fit_score", 0) >= MIN_FIT_SCORE:
            result["fetched_at"] = datetime.utcnow().isoformat() + "Z"
            result.pop("raw_text", None)
            result.pop("keyword_match", None)
            scored.append(result)

    scored.sort(key=lambda x: x.get("fit_score", 0), reverse=True)
    log.info(f"{len(scored)} opportunities meet fit threshold ≥{MIN_FIT_SCORE}")

    # Merge with existing (keep up to 90 days)
    existing = []
    if OUTPUT_PATH.exists():
        try:
            existing = json.loads(OUTPUT_PATH.read_text()).get("opportunities", [])
        except Exception:
            existing = []

    cutoff = datetime.utcnow() - timedelta(days=90)
    kept = [
        o for o in existing
        if o["id"] not in unique
        and datetime.fromisoformat(o.get("fetched_at", "2000-01-01T00:00:00").rstrip("Z")) > cutoff
    ]

    all_opps = scored + kept
    all_opps.sort(key=lambda x: x.get("fit_score", 0), reverse=True)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps({
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "run_id": uuid.uuid4().hex[:8],
        "opportunities": all_opps,
    }, indent=2))
    log.info(f"Wrote {len(all_opps)} total opportunities to {OUTPUT_PATH}")

    seen.update(unique.keys())
    save_seen(seen)
    log.info("Done.")


if __name__ == "__main__":
    main()
