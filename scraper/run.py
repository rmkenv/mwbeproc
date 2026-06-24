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

            # Extract title from the line containing PIN# — everything before "PIN#"
            # City Record format: "Language Access Services – Renewal – PIN#XXXXX – AMT: $X – TO: Vendor"
            title = ""
            for line in lines:
                if "PIN#" in line:
                    # Take everything before the PIN# marker
                    before_pin = line.split("PIN#")[0].strip()
                    # Clean trailing separators (–, -, —)
                    before_pin = re.sub(r"[\s\-–—]+$", "", before_pin).strip()
                    if len(before_pin) > 10:
                        title = before_pin[:150]
                    break

            # Fallback: first non-caps, non-boilerplate line
            if not title:
                for line in lines:
                    if line.isupper() and len(line) < 80:
                        continue
                    if any(line.startswith(p) for p in ("PIN#", "AMT:", "TO:", "E j", "Use the", "The City", "Vendors should")):
                        continue
                    if ". . ." in line or len(line) < 10:
                        continue
                    title = line[:150]
                    break

            if not title:
                title = f"{current_agency} — {matched_kw} procurement"

            # Skip if title is still boilerplate
            boilerplate = ["frequently review", "Compete To Win", "compete to win",
                           "Services (other than", "vendorsshould", "City Record Online"]
            if any(b.lower() in title.lower() for b in boilerplate):
                continue

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



# ── Source 4 & 5: Nassau + Suffolk via Playwright HTML extraction ─────────────

def render_and_parse(url: str, county: str) -> list[dict]:
    """
    Renders the procurement portal with Playwright (handles JS tables),
    extracts the rendered HTML, and parses with BeautifulSoup.
    No vision model needed — works on free Ollama tier.
    """
    results = []
    jurisdiction = "Nassau" if county == "Nassau" else "Suffolk"

    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(args=["--no-sandbox", "--disable-dev-shm-usage"])
            page = browser.new_page(viewport={"width": 1400, "height": 900})
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(5000)
            html = page.content()
            browser.close()
        log.info(f"{county}: page rendered, {len(html)} chars of HTML")
    except Exception as e:
        log.warning(f"{county}: Playwright failed: {e}")
        return []

    try:
        soup = BeautifulSoup(html, "html.parser")

        # Find all tables — try common selectors
        tables = (
            soup.find_all("table", class_=lambda c: c and any(x in str(c).lower() for x in ["irr", "grid", "result", "bid", "rfp"]))
            or soup.find_all("table")
        )

        if not tables:
            log.warning(f"{county}: no tables found in rendered HTML")
            return []

        for table in tables:
            rows = table.find_all("tr")
            if len(rows) < 2:
                continue

            # Get headers
            header_row = rows[0]
            headers = [th.get_text(strip=True).lower() for th in header_row.find_all(["th", "td"])]

            for row in rows[1:]:
                cols = row.find_all("td")
                if not cols:
                    continue

                col_texts = [c.get_text(strip=True) for c in cols]
                raw = " ".join(col_texts)
                if not raw.strip():
                    continue

                # Keyword filter
                matched_kw = next((kw for kw in KEYWORDS if kw.lower() in raw.lower()), None)
                if not matched_kw:
                    continue

                # Find link
                link = row.find("a")
                href = link.get("href", "") if link else ""
                if href and not href.startswith("http"):
                    base = "https://apex5.nassaucountyny.gov" if county == "Nassau" else "https://dpw.suffolkcountyny.gov"
                    href = base + "/" + href.lstrip("/")

                # Best guess at field positions
                title    = col_texts[0] if col_texts else raw[:80]
                due_date = next((t for t in col_texts if re.search(r"\d{1,2}/\d{1,2}/\d{2,4}", t)), "")
                doc_num  = re.sub(r"\s+", "-", col_texts[0])[:20] if col_texts else uuid.uuid4().hex[:6]

                results.append({
                    "id": f"{jurisdiction.upper()}-{doc_num}-{uuid.uuid4().hex[:4]}",
                    "title": title,
                    "agency": f"{county} County",
                    "jurisdiction": jurisdiction,
                    "source": f"{county} County Procurement Portal",
                    "source_url": href or url,
                    "amount": 0,
                    "due_date": due_date,
                    "issue_date": "",
                    "contract_type": "Solicitation",
                    "keyword_match": matched_kw,
                    "raw_text": raw[:500],
                })

        log.info(f"{county}: {len(results)} keyword-matched solicitations")
    except Exception as e:
        log.warning(f"{county}: HTML parse failed: {e}")

    return results


def fetch_nassau() -> list[dict]:
    return render_and_parse("https://apex5.nassaucountyny.gov/ords/f?p=533:226", "Nassau")


def fetch_suffolk() -> list[dict]:
    return render_and_parse("https://dpw.suffolkcountyny.gov/RFP/Offering_Search.aspx", "Suffolk")


# ── Source 6: NYC Council Legistar — advance intelligence ─────────────────────

def fetch_legistar_advance_intel() -> list[dict]:
    """
    NYC Council Legistar API — surfaces contract discussions, budget hearings,
    and legislation that signals an RFP is coming 3-6 months out.
    Public API, no key required.
    Monitors: Committee hearings mentioning immigration/legal services topics.
    """
    results  = []
    seen_ids = set()
    base_url = "https://webapi.legistar.com/v1/nyc"
    cutoff   = (datetime.now() - timedelta(days=DAYS_BACK)).strftime("%Y-%m-%d")

    # Search matters (legislation/resolutions/contract approvals)
    for keyword in ["immigration", "legal services", "immigrant", "asylum", "language access", "refugee"]:
        try:
            r = requests.get(
                f"{base_url}/matters",
                params={
                    "$filter": f"MatterLastModifiedUtc ge datetime'{cutoff}T00:00:00' and substringof('{keyword}', MatterTitle)",
                    "$top": 20,
                    "$orderby": "MatterLastModifiedUtc desc",
                },
                timeout=15,
                headers=HEADERS,
            )
            r.raise_for_status()
            matters = r.json()

            for m in matters:
                matter_id  = str(m.get("MatterId", ""))
                matter_type = m.get("MatterTypeName", "")
                title      = m.get("MatterTitle", "").strip()
                status     = m.get("MatterStatusName", "")
                body       = m.get("MatterBodyName", "")
                modified   = m.get("MatterLastModifiedUtc", "")[:10]

                if not title or matter_id in seen_ids:
                    continue
                seen_ids.add(matter_id)

                # Only keep relevant matter types
                relevant_types = ["Contract", "Budget", "Oversight", "Resolution",
                                  "Introduction", "Communication", "Report"]
                if not any(t.lower() in matter_type.lower() for t in relevant_types):
                    continue

                matched_kw = next((kw for kw in KEYWORDS if kw.lower() in title.lower()), keyword)

                results.append({
                    "id": f"LEGISTAR-{matter_id}",
                    "title": f"[COUNCIL SIGNAL] {title}",
                    "agency": body or "NYC Council",
                    "jurisdiction": "NYC",
                    "source": "NYC Council Legistar (Advance Intel)",
                    "source_url": f"https://legistar.council.nyc.gov/MatterDetail.aspx?ID={matter_id}&GUID=placeholder",
                    "amount": 0,
                    "due_date": "",
                    "issue_date": modified,
                    "contract_type": matter_type or "Council Action",
                    "keyword_match": matched_kw,
                    "raw_text": f"{title} {body} {status} {matter_type}",
                })

        except Exception as e:
            log.warning(f"Legistar matters failed for '{keyword}': {e}")

    # Also check upcoming committee hearings
    try:
        r = requests.get(
            f"{base_url}/events",
            params={
                "$filter": f"EventDate ge datetime'{datetime.now().strftime('%Y-%m-%d')}T00:00:00'",
                "$top": 50,
                "$orderby": "EventDate asc",
            },
            timeout=15,
            headers=HEADERS,
        )
        r.raise_for_status()
        events = r.json()

        for event in events:
            event_id   = str(event.get("EventId", ""))
            body       = event.get("EventBodyName", "")
            event_date = event.get("EventDate", "")[:10]
            location   = event.get("EventLocation", "")
            comment    = event.get("EventComment", "") or ""

            raw = f"{body} {comment}"
            matched_kw = next((kw for kw in KEYWORDS if kw.lower() in raw.lower()), None)
            if not matched_kw or event_id in seen_ids:
                continue
            seen_ids.add(event_id)

            results.append({
                "id": f"LEGISTAR-EVT-{event_id}",
                "title": f"[UPCOMING HEARING] {body}",
                "agency": body,
                "jurisdiction": "NYC",
                "source": "NYC Council Legistar (Upcoming Hearing)",
                "source_url": f"https://legistar.council.nyc.gov/Calendar.aspx",
                "amount": 0,
                "due_date": event_date,
                "issue_date": datetime.now().strftime("%Y-%m-%d"),
                "contract_type": "Hearing",
                "keyword_match": matched_kw,
                "raw_text": raw[:500],
            })

    except Exception as e:
        log.warning(f"Legistar events failed: {e}")

    log.info(f"Legistar advance intel: {len(results)} items")
    return results



# ── Deduplication ─────────────────────────────────────────────────────────────

def load_seen() -> set:
    if SEEN_PATH.exists():
        return set(json.loads(SEEN_PATH.read_text()))
    return set()

def save_seen(seen: set):
    SEEN_PATH.write_text(json.dumps(sorted(seen), indent=2))


# ── LLM scoring via Ollama Cloud ─────────────────────────────────────────────

def ollama_call(prompt: str, model: str) -> str:
    """Call Ollama Cloud API for text scoring."""
    base = OLLAMA_BASE_URL.rstrip("/")
    url  = f"{base}/api/chat"
    hdrs = {"Content-Type": "application/json"}
    if OLLAMA_API_KEY:
        hdrs["Authorization"] = f"Bearer {OLLAMA_API_KEY}"
    r = requests.post(
        url, headers=hdrs,
        json={"model": model, "messages": [{"role": "user", "content": prompt}], "stream": False},
        timeout=60,
    )
    if not r.ok:
        log.warning(f"Ollama error {r.status_code}: {r.text[:300]}")
        r.raise_for_status()
    content = r.json()["message"]["content"].strip()
    if "<think>" in content:
        content = content.split("</think>")[-1].strip()
    return content


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

    # NYC Council Legistar — advance intelligence (3-6 months ahead of RFPs)
    log.info("Fetching NYC Council Legistar advance intel...")
    raw += fetch_legistar_advance_intel()

    # Nassau and Suffolk — Playwright HTML extraction (no vision model needed)
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
