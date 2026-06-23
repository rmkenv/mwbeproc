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

# ── Source 1: NYC City Record — Daily PDF ────────────────────────────────────

def fetch_nyc_city_record_pdf() -> list[dict]:
    """
    Fetches today's NYC City Record print edition PDF via GetLatestPrintEditionUrl,
    extracts the PROCUREMENT section, parses individual entries, and keyword-filters.
    This is the authoritative daily source — updated every business day.
    """
    results  = []
    seen_ids = set()

    try:
        # Step 1: Get the PDF URL
        r = requests.get(
            "https://a856-cityrecord.nyc.gov/Home/GetLatestPrintEditionUrl",
            timeout=15, headers=HEADERS,
        )
        r.raise_for_status()
        pdf_url = r.text.strip()
        log.info(f"City Record PDF URL: {pdf_url}")

        # Step 2: Download the PDF
        pdf_r = requests.get(pdf_url, timeout=60, headers=HEADERS)
        pdf_r.raise_for_status()

        # Step 3: Extract text using pdfminer
        from pdfminer.high_level import extract_text
        from io import BytesIO
        text = extract_text(BytesIO(pdf_r.content))

        # Step 4: Find PROCUREMENT section
        proc_start = text.find("PROCUREMENT")
        if proc_start == -1:
            log.warning("City Record PDF: PROCUREMENT section not found")
            return []

        # Find end of procurement section (next major section)
        end_markers = ["PUBLIC COMMENT ON", "AGENCY RULES", "SPECIAL MATERIALS"]
        proc_end = len(text)
        for marker in end_markers:
            idx = text.find(marker, proc_start + 100)
            if idx != -1 and idx < proc_end:
                proc_end = idx

        procurement_text = text[proc_start:proc_end]

        # Step 5: Split by agency blocks (all-caps lines followed by content)
        import re
        # Each agency block starts with agency name in ALL CAPS
        # Split on lines that are all-caps and not too long (agency headers)
        lines = procurement_text.split("\n")
        current_agency = ""
        current_block  = []
        blocks         = []

        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            # Detect agency header: short all-caps line
            if stripped.isupper() and 3 < len(stripped) < 60 and not stripped.startswith("PIN") and not stripped.startswith("AMT"):
                if current_agency and current_block:
                    blocks.append((current_agency, "\n".join(current_block)))
                current_agency = stripped
                current_block  = []
            else:
                current_block.append(stripped)

        if current_agency and current_block:
            blocks.append((current_agency, "\n".join(current_block)))

        # Step 6: Parse each block into individual solicitation entries
        for agency, block_text in blocks:
            # Split on PIN# or E j (date markers) to find individual entries
            # Each entry typically has: title, type (SOLICITATION/AWARD), PIN, AMT
            entries = re.split(r"(?=PIN#|E\s+j\d)", block_text)

            for entry in entries:
                entry = entry.strip()
                if not entry or len(entry) < 20:
                    continue

                # Keyword filter
                matched_kw = next((kw for kw in KEYWORDS if kw.lower() in entry.lower()), None)
                if not matched_kw:
                    continue

                # Extract PIN
                pin_match = re.search(r"PIN#([\w\-]+)", entry)
                pin = pin_match.group(1) if pin_match else uuid.uuid4().hex[:8]

                # Extract amount
                amt_match = re.search(r"AMT:\s*\$([\d,\.]+)", entry)
                amount = float(amt_match.group(1).replace(",", "")) if amt_match else 0

                # Extract title — first meaningful line before type indicator
                title_match = re.search(r"([A-Z][A-Z\s\-\(\)\/,]{10,}?)\s*[-–]\s*(Renewal|Award|Solicitation|Request|Competitive|Negotiated|Sole Source|Intergovernmental)", entry)
                title = title_match.group(1).strip() if title_match else entry[:80].strip()

                # Notice type
                notice_type = "AWARD" if "AWARD" in entry[:200].upper() else \
                              "SOLICITATION" if "SOLICITATION" in entry[:200].upper() else \
                              "VENDOR LIST" if "VENDOR LIST" in entry[:200].upper() else "Notice"

                uid = f"CROL-{pin}"
                if uid in seen_ids:
                    continue
                seen_ids.add(uid)

                results.append({
                    "id": uid,
                    "title": title,
                    "agency": agency.title(),
                    "jurisdiction": "NYC",
                    "source": "NYC City Record (PDF)",
                    "source_url": pdf_url,
                    "amount": amount,
                    "due_date": "",
                    "issue_date": datetime.now().strftime("%Y-%m-%d"),
                    "contract_type": notice_type,
                    "keyword_match": matched_kw,
                    "raw_text": entry[:500],
                })

        log.info(f"NYC City Record PDF: {len(results)} keyword-matched procurement entries")

    except ImportError:
        log.warning("pdfminer not installed — skipping City Record PDF. Add 'pdfminer.six' to requirements.")
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

def screenshot_and_extract(url: str, county: str) -> list[dict]:
    """
    Renders the procurement portal URL using Playwright headless Chromium,
    takes a full-page screenshot, and sends it to the Ollama vision model
    to extract all solicitation entries as structured JSON.
    """
    import base64

    results = []

    # Step 1: Render page with Playwright
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(args=["--no-sandbox", "--disable-dev-shm-usage"])
            page = browser.new_page(viewport={"width": 1400, "height": 900})
            page.goto(url, wait_until="networkidle", timeout=30000)
            # Wait a bit for JS-rendered tables to populate
            page.wait_for_timeout(3000)
            screenshot_bytes = page.screenshot(full_page=True)
            browser.close()
        log.info(f"{county}: page rendered, screenshot {len(screenshot_bytes)} bytes")
    except Exception as e:
        log.warning(f"{county}: Playwright failed: {e}")
        return []

    # Step 2: Send to vision model
    try:
        img_b64 = base64.b64encode(screenshot_bytes).decode("utf-8")
        base = OLLAMA_BASE_URL.rstrip("/")
        chat_url = f"{base}/api/chat" if not base.endswith("/api") else f"{base}/chat"

        hdrs = {"Content-Type": "application/json"}
        if OLLAMA_API_KEY:
            hdrs["Authorization"] = f"Bearer {OLLAMA_API_KEY}"

        # Use vision-capable model — qwen2.5vl or llava
        vision_model = os.getenv("OLLAMA_VISION_MODEL", OLLAMA_MODEL)

        r = requests.post(
            chat_url,
            json={
                "model": vision_model,
                "messages": [{
                    "role": "user",
                    "content": VISION_PROMPT,
                    "images": [img_b64],
                }],
                "stream": False,
            },
            headers=hdrs,
            timeout=90,
        )
        r.raise_for_status()
        content = r.json()["message"]["content"].strip()

        # Strip think tags and fences
        if "<think>" in content:
            content = content.split("</think>")[-1].strip()
        if content.startswith("```"):
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]

        entries = json.loads(content.strip())
        if not isinstance(entries, list):
            entries = []

        log.info(f"{county}: vision model extracted {len(entries)} entries")

    except Exception as e:
        log.warning(f"{county}: vision extraction failed: {e}")
        return []

    # Step 3: Keyword-filter and normalize
    jurisdiction = "Nassau" if county == "Nassau" else "Suffolk"
    source_name  = f"{county} County Procurement Portal"

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
            "source": source_name,
            "source_url": url,
            "amount": 0,
            "due_date": entry.get("due_date", ""),
            "issue_date": entry.get("issue_date", ""),
            "contract_type": entry.get("type", "Solicitation"),
            "keyword_match": matched,
            "raw_text": raw,
        })

    log.info(f"{county}: {len(results)} keyword-matched after filtering")
    return results


def fetch_nassau() -> list[dict]:
    return screenshot_and_extract(
        "https://apex5.nassaucountyny.gov/ords/f?p=533:226",
        "Nassau",
    )


def fetch_suffolk() -> list[dict]:
    return screenshot_and_extract(
        "https://dpw.suffolkcountyny.gov/RFP/Offering_Search.aspx",
        "Suffolk",
    )


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

    seen.update(unique.keys())
    save_seen(seen)
    log.info("Done.")


if __name__ == "__main__":
    main()
