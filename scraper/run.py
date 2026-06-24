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

OLLAMA_BASE_URL     = os.getenv("OLLAMA_BASE_URL", "https://ollama.com")
OLLAMA_MODEL        = os.getenv("OLLAMA_MODEL", "gpt-oss:20b")
OLLAMA_VISION_MODEL = os.getenv("OLLAMA_VISION_MODEL", "gemma4:12b")
OLLAMA_API_KEY      = os.getenv("OLLAMA_API_KEY", "")
FIRM_NAME           = os.getenv("FIRM_NAME", "IQSpatial Legal")
MIN_FIT_SCORE       = int(os.getenv("MIN_FIT_SCORE", "5"))
SAM_API_KEY         = os.getenv("SAM_API_KEY", "")
DAYS_BACK           = 30

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

# ── Source 1: NYC City Record — Daily PDF ────────────────────────────────────

def fetch_nyc_city_record_pdf() -> list[dict]:
    """
    NYC City Record PDF parser.
    Key insight: the PDF has a TABLE OF CONTENTS near the top that also contains
    the word "PROCUREMENT" — must skip past it to find actual entries.
    Real entries contain PIN# numbers. Find the first PIN# and work from there.
    """
    import re
    results  = []
    seen_ids = set()

    try:
        r = requests.get(
            "https://a856-cityrecord.nyc.gov/Home/GetLatestPrintEditionUrl",
            timeout=15, headers=HEADERS,
        )
        r.raise_for_status()
        pdf_url = r.text.strip()
        log.info(f"City Record PDF URL: {pdf_url}")

        pdf_r = requests.get(pdf_url, timeout=60, headers=HEADERS)
        pdf_r.raise_for_status()
        log.info(f"City Record PDF: {len(pdf_r.content)} bytes")

        from pdfminer.high_level import extract_text
        from io import BytesIO
        text = extract_text(BytesIO(pdf_r.content))
        log.info(f"City Record PDF: {len(text)} chars extracted")

        # Find the REAL procurement section — skip the TOC
        # Strategy: find the first PIN# which only appears in actual entries
        first_pin = text.find("PIN#")
        if first_pin == -1:
            log.warning("City Record PDF: no PIN# found — no procurement entries today")
            return []

        # Walk backward from first PIN# to find the PROCUREMENT section header
        search_back = text[max(0, first_pin - 3000):first_pin]
        proc_offset = search_back.rfind("PROCUREMENT")
        if proc_offset != -1:
            proc_start = max(0, first_pin - 3000) + proc_offset
        else:
            # No header found, start from a bit before the first PIN#
            proc_start = max(0, first_pin - 500)

        # End section
        proc_end = text.find("PUBLIC COMMENT ON CONTRACT AWARDS", proc_start)
        if proc_end == -1:
            proc_end = text.find("PUBLIC COMMENT ON", proc_start)
        if proc_end == -1:
            proc_end = min(proc_start + 80000, len(text))

        procurement_text = text[proc_start:proc_end]
        log.info(f"City Record PDF: real PROCUREMENT section {len(procurement_text)} chars (starts at {proc_start})")

        # Count total PINs to verify we're in the right section
        pin_count = len(re.findall(r"PIN#", procurement_text))
        log.info(f"City Record PDF: {pin_count} PIN# entries found in section")

        # Split on "E j" date markers — each entry ends with one
        raw_entries = re.split(r"\nE\s+j[\w\-]+\s*\n", procurement_text)
        log.info(f"City Record PDF: split into {len(raw_entries)} blocks")

        current_agency = "NYC Agency"

        for raw in raw_entries:
            raw = raw.strip()
            if not raw or len(raw) < 30:
                continue

            # Skip TOC-style lines (dot leaders like ". . . . . 2670")
            if re.search(r"\.\s*\.\s*\.\s*\.\s*\d{4}", raw):
                continue

            # Skip boilerplate blocks
            if any(bp in raw for bp in [
                "Compete To Win", "compete to win", "CompeteToWin",
                "Vendors List brings contracting",
                "Office of the Corporate Secretary",
                "The City Record Online",
                "CITY RECORD",
            ]):
                continue

            # Update current agency from all-caps lines at start of block
            lines = [l.strip() for l in raw.split("\n") if l.strip()]
            for line in lines[:5]:
                if (line.isupper() and 5 < len(line) < 80 
                    and not any(line.startswith(p) for p in 
                        ("PIN", "AMT", "TO:", "NYC", "FY", "THE ", "USE "))):
                    current_agency = line.title()
                    break

            # Keyword filter
            matched_kw = next((kw for kw in KEYWORDS if kw.lower() in raw.lower()), None)
            if not matched_kw:
                continue

            # REQUIRE PIN# — entries without a PIN are boilerplate/headers, not solicitations
            pin_match = re.search(r"PIN#\s*([\w\-]+)", raw)
            if not pin_match:
                continue
            pin = pin_match.group(1)

            # Extract amount
            amt_match = re.search(r"AMT:\s*\$([\d,\.]+)", raw)
            amount = float(amt_match.group(1).replace(",", "")) if amt_match else 0

            # Extract vendor
            vendor_match = re.search(r"\bTO:\s*([^,\n]{5,80})", raw)
            vendor = vendor_match.group(1).strip() if vendor_match else ""

            # Build title: first line with real content (not all-caps header, not PIN/AMT)
            title = ""
            for line in lines:
                # Skip agency headers
                if line.isupper() and len(line) < 80:
                    continue
                # Skip metadata lines
                if any(line.startswith(p) for p in ("PIN#", "AMT:", "TO:", "E j", "Use the", "The City")):
                    continue
                # Skip dot-leader lines
                if ". . ." in line:
                    continue
                if len(line) > 15:
                    title = line[:120]
                    break
            if not title:
                title = f"{current_agency} — {matched_kw} procurement"

            # Notice type
            raw_upper = raw.upper()
            if "AWARD" in raw_upper[:400]:
                notice_type = "AWARD"
            elif "SOLICITATION" in raw_upper[:400]:
                notice_type = "SOLICITATION"
            elif "INTENT TO AWARD" in raw_upper:
                notice_type = "INTENT TO AWARD"
            elif "VENDOR LIST" in raw_upper:
                notice_type = "VENDOR LIST"
            else:
                notice_type = "Notice"

            uid = f"CROL-{pin}"
            if uid in seen_ids:
                continue
            seen_ids.add(uid)

            results.append({
                "id": uid,
                "title": title,
                "agency": current_agency,
                "jurisdiction": "NYC",
                "source": "NYC City Record (PDF)",
                "source_url": pdf_url,
                "amount": amount,
                "due_date": "",
                "issue_date": datetime.now().strftime("%Y-%m-%d"),
                "contract_type": notice_type,
                "keyword_match": matched_kw,
                "raw_text": raw[:500],
            })

        log.info(f"NYC City Record PDF: {len(results)} keyword-matched entries")

    except ImportError:
        log.warning("pdfminer not installed — skipping City Record PDF.")
    except Exception as e:
        log.warning(f"City Record PDF fetch failed: {e}")

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


# ── Source 4 & 5: Nassau + Suffolk via Playwright + Vision Model ──────────────

VISION_PROMPT = """You are reviewing a screenshot of a government procurement portal page.
Extract ALL solicitation/bid entries visible in the table.
Return ONLY a JSON array — no markdown, no preamble.

Each item must have:
{{
  "title": "solicitation title or description",
  "doc_number": "bid/RFP/doc number if visible",
  "type": "RFP|RFQ|IFB|Bid|Solicitation",
  "due_date": "due date if visible, else empty string",
  "issue_date": "issue/posted date if visible, else empty string",
  "department": "department or agency name if visible, else empty string"
}}

If no solicitations are visible, return [].
"""


def ollama_call(prompt: str, model: str, image_b64: str = None) -> str:
    """
    Call Ollama Cloud API.
    Direct API: https://ollama.com/api/chat with Bearer token.
    Logs full response body on error for debugging.
    """
    base = OLLAMA_BASE_URL.rstrip("/")
    url  = f"{base}/api/chat"

    hdrs = {"Content-Type": "application/json"}
    if OLLAMA_API_KEY:
        hdrs["Authorization"] = f"Bearer {OLLAMA_API_KEY}"

    # Build message content
    if image_b64:
        # Ollama vision format: images array in the message
        messages = [{"role": "user", "content": prompt, "images": [image_b64]}]
    else:
        messages = [{"role": "user", "content": prompt}]

    r = requests.post(
        url,
        headers=hdrs,
        json={"model": model, "messages": messages, "stream": False},
        timeout=90,
    )

    if not r.ok:
        # Log full response body to help diagnose 404/403
        log.warning(f"Ollama API error {r.status_code} for model '{model}': {r.text[:500]}")
        r.raise_for_status()

    content = r.json()["message"]["content"].strip()

    # Strip thinking tags
    if "<think>" in content:
        content = content.split("</think>")[-1].strip()

    return content


def screenshot_and_extract(url: str, county: str) -> list[dict]:
    """
    Playwright screenshot → Ollama vision model (gemma4:12b) → JSON extraction.
    """
    import base64
    results = []

    # Step 1: Playwright render
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(args=["--no-sandbox", "--disable-dev-shm-usage"])
            page = browser.new_page(viewport={"width": 1400, "height": 900})
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(5000)
            screenshot_bytes = page.screenshot(full_page=True)
            browser.close()
        log.info(f"{county}: rendered, {len(screenshot_bytes)} bytes")
    except Exception as e:
        log.warning(f"{county}: Playwright failed: {e}")
        return []

    # Step 2: Vision extraction
    try:
        img_b64 = base64.b64encode(screenshot_bytes).decode("utf-8")
        content = ollama_call(VISION_PROMPT, model=OLLAMA_VISION_MODEL, image_b64=img_b64)

        if content.startswith("```"):
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]

        entries = json.loads(content.strip())
        if not isinstance(entries, list):
            entries = []
        log.info(f"{county}: extracted {len(entries)} entries")
    except requests.exceptions.HTTPError as e:
        if e.response is not None and e.response.status_code == 403:
            log.warning(f"{county}: vision model '{OLLAMA_VISION_MODEL}' requires subscription upgrade — skipping. Upgrade at ollama.com/upgrade")
        else:
            log.warning(f"{county}: vision failed: {e}")
        return []
    except Exception as e:
        log.warning(f"{county}: vision failed: {e}")
        return []

    # Step 3: Keyword filter
    jurisdiction = "Nassau" if county == "Nassau" else "Suffolk"
    for entry in entries:
        title   = entry.get("title", "").strip()
        raw     = f"{title} {entry.get('department', '')} {entry.get('type', '')}"
        matched = next((kw for kw in KEYWORDS if kw.lower() in raw.lower()), None)
        if not matched or not title:
            continue
        doc_num = entry.get("doc_number", uuid.uuid4().hex[:6])
        results.append({
            "id": f"{jurisdiction.upper()}-{doc_num}",
            "title": title,
            "agency": entry.get("department", f"{county} County"),
            "jurisdiction": jurisdiction,
            "source": f"{county} County Procurement Portal",
            "source_url": url,
            "amount": 0,
            "due_date": entry.get("due_date", ""),
            "issue_date": entry.get("issue_date", ""),
            "contract_type": entry.get("type", "Solicitation"),
            "keyword_match": matched,
            "raw_text": raw,
        })

    log.info(f"{county}: {len(results)} keyword-matched")
    return results


def fetch_nassau() -> list[dict]:
    return screenshot_and_extract("https://apex5.nassaucountyny.gov/ords/f?p=533:226", "Nassau")


def fetch_suffolk() -> list[dict]:
    return screenshot_and_extract("https://dpw.suffolkcountyny.gov/RFP/Offering_Search.aspx", "Suffolk")

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
    prompt = SCORE_PROMPT.format(firm=FIRM_NAME, **opp)
    log.info(f"Scoring '{opp['title'][:60]}' with {OLLAMA_MODEL}")
    try:
        content = ollama_call(prompt, model=OLLAMA_MODEL)
        if content.startswith("```"):
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]
        return {**opp, **json.loads(content.strip())}
    except Exception as e:
        log.warning(f"LLM scoring failed for '{opp['title']}': {e}")
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

    # NYC City Record — daily PDF (authoritative source)
    log.info("Fetching NYC City Record daily PDF...")
    raw += fetch_nyc_city_record_pdf()

    # Nassau and Suffolk — scrape all open solicitations once, keyword-filter internally
    log.info("Fetching Nassau County solicitations...")
    raw += fetch_nassau()
    log.info("Fetching Suffolk County solicitations...")
    raw += fetch_suffolk()

    # Keyword-based sources
    for kw in KEYWORDS:
        log.info(f"Fetching keyword: {kw}")
        raw += fetch_sam_gov(kw)
        raw += fetch_nys_contract_reporter(kw)

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

    seen.update(o["id"] for o in all_opps)
    save_seen(seen)
    log.info("Done.")


if __name__ == "__main__":
    main()
