"""
MWBE Procurement Monitor — scraper entry point.
Scrapes portals → deduplicates → LLM scores → writes public/data/opportunities.json
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

# ── Config ──────────────────────────────────────────────────────────────────

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL    = os.getenv("OLLAMA_MODEL", "llama3.1:8b")
FIRM_NAME       = os.getenv("FIRM_NAME", "IQSpatial Legal")
MIN_FIT_SCORE   = int(os.getenv("MIN_FIT_SCORE", "5"))
DAYS_BACK       = 30

OUTPUT_PATH     = Path(__file__).parent.parent / "public" / "data" / "opportunities.json"
SEEN_PATH       = Path(__file__).parent / "seen_ids.json"

KEYWORDS = [
    "immigration", "immigrant", "legal services", "legal aid",
    "asylum", "removal defense", "naturalization", "DACA",
    "refugee", "community legal", "SIJS", "TPS", "humanitarian",
    "know your rights", "U visa", "VAWA", "language access",
]

# ── Scrapers ─────────────────────────────────────────────────────────────────

def fetch_nyc_opendata(keyword: str) -> list[dict]:
    """NYC contracts via Open Data API (no key required)."""
    url = "https://data.cityofnewyork.us/resource/fmzz-s9dj.json"
    params = {
        "$where": f"UPPER(contract_purpose) LIKE '%{keyword.upper()}%'",
        "$limit": 30,
        "$order": "start_date DESC",
    }
    try:
        r = requests.get(url, params=params, timeout=15)
        r.raise_for_status()
        results = []
        for c in r.json():
            results.append({
                "id": c.get("contract_id", str(uuid.uuid4())[:8]),
                "title": c.get("contract_purpose", "Unknown"),
                "agency": c.get("agency_name", ""),
                "jurisdiction": "NYC",
                "source": "NYC Open Data / PASSPort",
                "source_url": "https://www1.nyc.gov/site/mocs/systems/passport.page",
                "amount": float(c.get("current_amount", 0) or 0),
                "start_date": c.get("start_date", ""),
                "due_date": c.get("end_date", ""),
                "issue_date": c.get("start_date", ""),
                "contract_type": c.get("contract_type", "Contract"),
                "keyword_match": keyword,
                "raw_text": f"{c.get('contract_purpose','')} {c.get('agency_name','')}",
            })
        return results
    except Exception as e:
        log.warning(f"NYC Open Data failed for '{keyword}': {e}")
        return []


def fetch_checkbook(keyword: str) -> list[dict]:
    """Checkbook NYC contracts."""
    url = "https://www.checkbooknyc.com/api/contracts/search"
    start = (datetime.now() - timedelta(days=DAYS_BACK)).strftime("%Y%m%d")
    params = {
        "search_type": "contracts", "value": keyword,
        "start_date": start, "response_format": "json",
        "records_from": 0, "record_size": 20,
    }
    try:
        r = requests.get(url, params=params, timeout=15)
        r.raise_for_status()
        data = r.json()
        contracts = data.get("contracts", {}).get("contract", [])
        if isinstance(contracts, dict):
            contracts = [contracts]
        results = []
        for c in contracts:
            results.append({
                "id": f"CB-{c.get('contract_id', uuid.uuid4().hex[:8])}",
                "title": c.get("contract_purpose", c.get("vendor_name", "Unknown")),
                "agency": c.get("agency_name", ""),
                "jurisdiction": "NYC",
                "source": "Checkbook NYC",
                "source_url": f"https://www.checkbooknyc.com/contract_details/contractid/{c.get('contract_id','')}",
                "amount": float(c.get("current_amount", 0) or 0),
                "due_date": c.get("end_date", ""),
                "issue_date": c.get("start_date", ""),
                "contract_type": c.get("contract_type", "Contract"),
                "keyword_match": keyword,
                "raw_text": f"{c.get('contract_purpose','')} {c.get('agency_name','')} {c.get('vendor_name','')}",
            })
        return results
    except Exception as e:
        log.warning(f"Checkbook failed for '{keyword}': {e}")
        return []


def fetch_nys_contract_reporter(keyword: str) -> list[dict]:
    """NYS Contract Reporter via form POST."""
    session = requests.Session()
    session.headers["User-Agent"] = "Mozilla/5.0 (compatible; MWBEMonitor/1.0)"
    try:
        session.get("https://www.nyscr.ny.gov/oppSrchForm.cfm", timeout=10)
        start = (datetime.now() - timedelta(days=DAYS_BACK)).strftime("%m/%d/%Y")
        end   = datetime.now().strftime("%m/%d/%Y")
        resp  = session.post(
            "https://www.nyscr.ny.gov/oppList.cfm",
            data={"oppType": "ALL", "keyword": keyword, "dateFrom": start, "dateTo": end, "submit": "Search"},
            timeout=20,
        )
        soup = BeautifulSoup(resp.text, "html.parser")
        results = []
        for row in soup.select("table.resultsTable tr:not(:first-child)"):
            cols = row.find_all("td")
            if len(cols) < 5:
                continue
            link = cols[1].find("a")
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


def fetch_nassau(keyword: str) -> list[dict]:
    """Nassau County bids page (basic scrape)."""
    try:
        r = requests.get("https://www.nassaucountyny.gov/1085/Procurement", timeout=15,
                         headers={"User-Agent": "Mozilla/5.0"})
        soup = BeautifulSoup(r.text, "html.parser")
        results = []
        for link in soup.find_all("a", string=lambda t: t and keyword.lower() in t.lower()):
            href = link.get("href", "https://www.nassaucountyny.gov/1085/Procurement")
            if not href.startswith("http"):
                href = "https://www.nassaucountyny.gov" + href
            results.append({
                "id": f"NASSAU-{uuid.uuid4().hex[:6]}",
                "title": link.get_text(strip=True),
                "agency": "Nassau County",
                "jurisdiction": "Nassau",
                "source": "Nassau County Portal",
                "source_url": href,
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


def fetch_suffolk(keyword: str) -> list[dict]:
    """Suffolk County procurement page (basic scrape)."""
    try:
        r = requests.get(
            "https://www.suffolkcountyny.gov/Departments/County-Executive/Procurement",
            timeout=15, headers={"User-Agent": "Mozilla/5.0"},
        )
        soup = BeautifulSoup(r.text, "html.parser")
        results = []
        for link in soup.find_all("a", string=lambda t: t and keyword.lower() in t.lower()):
            href = link.get("href", "https://www.suffolkcountyny.gov")
            if not href.startswith("http"):
                href = "https://www.suffolkcountyny.gov" + href
            results.append({
                "id": f"SUFFOLK-{uuid.uuid4().hex[:6]}",
                "title": link.get_text(strip=True),
                "agency": "Suffolk County",
                "jurisdiction": "Suffolk",
                "source": "Suffolk County Portal",
                "source_url": href,
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


# ── LLM scoring ──────────────────────────────────────────────────────────────

SCORE_PROMPT = """You are a procurement analyst for {firm}, an MWBE-certified immigration legal services firm.
Evaluate this government opportunity and respond ONLY with a JSON object — no markdown, no preamble.

Opportunity:
Title: {title}
Agency: {agency}
Jurisdiction: {jurisdiction}
Type: {contract_type}
Amount: ${amount}
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
    prompt = SCORE_PROMPT.format(firm=FIRM_NAME, **opp)
    try:
        r = requests.post(
            f"{OLLAMA_BASE_URL}/api/chat",
            json={
                "model": OLLAMA_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
            },
            timeout=60,
        )
        r.raise_for_status()
        content = r.json()["message"]["content"].strip()
        # Strip markdown fences if present
        if content.startswith("```"):
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]
        scored = json.loads(content.strip())
        return {**opp, **scored}
    except Exception as e:
        log.warning(f"LLM scoring failed for '{opp['title']}': {e}")
        # Fallback: basic keyword scoring
        text = opp.get("raw_text", "").lower()
        score = sum(3 if k in text else 0 for k in ["immigration", "legal services", "removal defense", "asylum"])
        score = min(max(score, 1), 10)
        return {
            **opp,
            "fit_score": score,
            "action": "PURSUE" if score >= 7 else "MONITOR" if score >= 5 else "SKIP",
            "summary": f"{opp['title']} from {opp['agency']}. Keyword match on '{opp['keyword_match']}'.",
            "keyword_matches": [opp["keyword_match"]],
            "certifications_required": [],
        }


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    log.info("Starting MWBE procurement scrape run")
    seen = load_seen()
    raw: list[dict] = []

    for kw in KEYWORDS:
        log.info(f"Fetching keyword: {kw}")
        raw += fetch_nyc_opendata(kw)
        raw += fetch_checkbook(kw)
        raw += fetch_nys_contract_reporter(kw)
        raw += fetch_nassau(kw)
        raw += fetch_suffolk(kw)

    # Deduplicate by id
    unique = {}
    for o in raw:
        if o["id"] not in seen and o["id"] not in unique:
            unique[o["id"]] = o
    log.info(f"Found {len(unique)} new unique opportunities")

    # Score each
    scored = []
    for opp in unique.values():
        result = score_opportunity(opp)
        if result and result.get("fit_score", 0) >= MIN_FIT_SCORE:
            result["fetched_at"] = datetime.utcnow().isoformat() + "Z"
            # Clean up internal field
            result.pop("raw_text", None)
            result.pop("keyword_match", None)
            scored.append(result)

    scored.sort(key=lambda x: x.get("fit_score", 0), reverse=True)
    log.info(f"{len(scored)} opportunities meet fit threshold ≥{MIN_FIT_SCORE}")

    # Load existing data and merge
    existing = []
    if OUTPUT_PATH.exists():
        try:
            existing = json.loads(OUTPUT_PATH.read_text()).get("opportunities", [])
        except Exception:
            existing = []

    # Keep existing opps not in this run (up to 90 days)
    cutoff = datetime.utcnow() - timedelta(days=90)
    kept = [
        o for o in existing
        if o["id"] not in unique
        and datetime.fromisoformat(o.get("fetched_at", "2000-01-01T00:00:00").rstrip("Z")) > cutoff
    ]

    all_opps = scored + kept
    all_opps.sort(key=lambda x: x.get("fit_score", 0), reverse=True)

    output = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "run_id": uuid.uuid4().hex[:8],
        "opportunities": all_opps,
    }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(output, indent=2))
    log.info(f"Wrote {len(all_opps)} total opportunities to {OUTPUT_PATH}")

    # Update seen IDs
    seen.update(unique.keys())
    save_seen(seen)
    log.info("Done.")


if __name__ == "__main__":
    main()
