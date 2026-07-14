"""
NYC City Record — the only source this project uses.

Two ways in, and they complement each other:

  1. City Record Online (CROL) via NYC Open Data / Socrata, dataset dg92-zbpx.
     This is the SEARCHABLE database behind the paper. Every notice ever
     published lives here with structured fields: PIN, due date, contract
     amount, selection method, and — the part that actually matters for
     business development — the contracting officer's name and email.

  2. The daily print edition PDF. Open Data can lag the printed edition by a
     day, so this is the same-day safety net. Anything it finds gets folded
     into the CROL record for the same PIN when the dataset catches up.

Field names below are the Socrata snake_case API names, which are NOT the
column titles shown in the CSV export (RequestID vs request_id). Getting this
wrong is silent: you get 200 OK, rows come back, every field reads as empty,
and the run reports "no matches today."
"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from io import BytesIO

import requests

log = logging.getLogger(__name__)

DATASET = "dg92-zbpx"
SODA_URL = f"https://data.cityofnewyork.us/resource/{DATASET}.json"
NOTICE_URL = "https://a856-cityrecord.nyc.gov/RequestDetail/{}"
LATEST_PDF = "https://a856-cityrecord.nyc.gov/Home/GetLatestPrintEditionUrl"

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; CityRecordMonitor/1.0)"}

# Verified against the dataset's SoQL schema.
FIELDS = [
    "request_id", "start_date", "end_date", "agency_name",
    "type_of_notice_description", "category_description", "short_title",
    "selection_method_description", "section_name", "pin", "due_date",
    "contact_name", "contact_phone", "email", "contract_amount",
    "additional_description_1", "additional_description_2",
    "additional_description_3", "vendor_name", "address_to_request",
    "document_links",
]

# What a notice IS, normalized from type_of_notice_description.
SOLICITATION = "SOLICITATION"   # open — you can respond
INTENT = "INTENT"               # intent to award — you can still object/compete
AWARD = "AWARD"                 # done — market intel on who's winning
OTHER = "OTHER"


@dataclass
class Status:
    name: str
    ok: bool = True
    found: int = 0
    queries: int = 0
    error: str = ""
    note: str = ""

    def as_dict(self) -> dict:
        return {"source": self.name, "ok": self.ok, "found": self.found,
                "queries": self.queries, "error": self.error[:300], "note": self.note}


def stable_id(prefix: str, native: str) -> str:
    return f"{prefix}-{hashlib.sha1(f'{prefix}:{native}'.encode()).hexdigest()[:12]}"


def norm_date(v) -> str:
    if not v:
        return ""
    v = str(v).strip()
    for f in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d",
              "%m/%d/%Y", "%m/%d/%y", "%m-%d-%Y", "%m-%d-%y"):
        try:
            return datetime.strptime(v, f).strftime("%Y-%m-%d")
        except ValueError:
            pass
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", v)
    if m:
        return m.group(0)
    m = re.search(r"(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})", v)
    if m:
        y = int(m.group(3))
        y += 2000 if y < 100 else 0
        return f"{y}-{int(m.group(1)):02d}-{int(m.group(2)):02d}"
    return ""


def money(v) -> float:
    if not v:
        return 0.0
    try:
        return float(re.sub(r"[^\d.]", "", str(v)) or 0)
    except ValueError:
        return 0.0


def classify(notice_type: str) -> str:
    t = (notice_type or "").lower()
    if "intent" in t:
        return INTENT
    if "solicitation" in t or "vendor list" in t:
        return SOLICITATION
    if "award" in t:
        return AWARD
    return OTHER


# ── 1. CROL search (the main event) ──────────────────────────────────────────

def _row_to_record(row: dict) -> dict | None:
    rid = str(row.get("request_id") or "").strip()
    title = (row.get("short_title") or "").strip()
    if not rid or not title:
        return None

    body = " ".join(str(row.get(f, "")) for f in (
        "short_title", "additional_description_1", "additional_description_2",
        "additional_description_3", "category_description",
        "selection_method_description", "agency_name",
    )).strip()

    notice_type = row.get("type_of_notice_description") or "Notice"
    selection = row.get("selection_method_description") or ""

    return {
        "id": stable_id("CROL", rid),
        "request_id": rid,
        "title": title[:200],
        "agency": row.get("agency_name") or "NYC Agency",
        "section": row.get("section_name") or "",
        "category": row.get("category_description") or "",
        "notice_type": notice_type,
        "record_type": classify(notice_type),
        "selection_method": selection,
        # M/WBE noncompetitive small purchases are the single most relevant
        # procurement vehicle for a certified firm — flag them loudly.
        "mwbe_vehicle": bool(re.search(r"m/?wbe", f"{selection} {notice_type}", re.I)),
        "pin": (row.get("pin") or "").strip(),
        "amount": money(row.get("contract_amount")),
        "vendor": (row.get("vendor_name") or "").strip(),
        "due_date": norm_date(row.get("due_date")),
        "issue_date": norm_date(row.get("start_date")),
        # The contracting officer. This is why CROL beats the PDF: you get a
        # name and an email to actually follow up on.
        "contact_name": (row.get("contact_name") or "").strip(),
        "contact_email": (row.get("email") or "").strip(),
        "contact_phone": (row.get("contact_phone") or "").strip(),
        "address": (row.get("address_to_request") or "").strip(),
        "source": "City Record Online",
        "source_url": NOTICE_URL.format(rid),
        "raw_text": body[:2000],
    }


def search_crol(terms: list[str], days_back: int = 45,
                app_token: str = "", sections: tuple = ("Procurement",)) -> tuple[list[dict], Status]:
    """Full-text search CROL for each term. $q searches across all columns, so a
    notice matches whether the keyword is in the title or buried in the scope
    description — which is where 'immigration legal services' usually lives."""
    st = Status("City Record Online")
    since = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%dT00:00:00")
    headers = dict(HEADERS)
    if app_token:
        headers["X-App-Token"] = app_token

    out: dict[str, dict] = {}

    for term in terms:
        st.queries += 1
        params = {
            "$select": ",".join(FIELDS),
            "$q": term,
            "$where": f"start_date > '{since}'",
            "$order": "start_date DESC",
            "$limit": 500,
        }
        try:
            r = requests.get(SODA_URL, params=params, headers=headers, timeout=45)
            if r.status_code == 400:
                # Date column type could change; degrade to unfiltered + local filter
                # rather than losing the source entirely.
                log.warning(f"'{term}': $where rejected ({r.text[:120]}) — retrying unfiltered")
                params.pop("$where")
                r = requests.get(SODA_URL, params=params, headers=headers, timeout=45)
            r.raise_for_status()
            rows = r.json()
        except Exception as e:
            st.ok = False
            st.error = f"{type(e).__name__}: {e}"
            log.warning(f"CROL '{term}' failed: {e}")
            continue

        if rows and st.found == 0 and not any(r_.get("request_id") for r_ in rows[:3]):
            # Schema drift tripwire: rows came back but the fields are all empty,
            # which means the API names changed under us. Fail loudly.
            st.ok = False
            st.error = (f"Rows returned but 'request_id' is absent — Socrata field "
                        f"names may have changed. Got: {sorted(rows[0].keys())[:8]}")
            log.error(st.error)
            continue

        for row in rows:
            rec = _row_to_record(row)
            if not rec:
                continue
            if sections and rec["section"] and rec["section"] not in sections:
                continue
            if norm_date(row.get("start_date")) < since[:10]:
                continue
            rec["matched_terms"] = sorted(set(out.get(rec["id"], {}).get("matched_terms", []) + [term]))
            out[rec["id"]] = rec

    st.found = len(out)
    if not out and st.ok:
        st.note = f"No procurement notices matched in the last {days_back} days."
    return list(out.values()), st


# ── 2. Today's print edition (same-day safety net) ───────────────────────────

BOILERPLATE = ("Compete To Win", "HHS ACCELERATOR PREQUALIFICATION",
               "The City Record Online", "Vendors List brings contracting")


# Lines that are structural headers, not part of a notice title.
_HEADERS = re.compile(
    r"^(AWARD|SOLICITATION|INTENT TO AWARD|VENDOR LIST|NOTICE|"
    r"Goods|Services \(other than human services\)|Human Services/Client Services|"
    r"Construction/Construction Services)$", re.I)


def _pdf_title(lines: list[str]) -> str:
    """City Record notices read:

        HOMELESS SERVICES              <- agency (caps)
         SOLICITATION                  <- notice type
        Services (other than human services)
        07126B0002-DHS IMMIGRATION LEGAL SERVICES FOR SHELTER RESIDENTS -
        Competitive Sealed Bids - PIN#07126B0002 - Due 8-24-26 at 2:00 P.M.

    The title wraps, and the PIN lands on a later line — so reading only the
    line containing PIN# yields "Competitive Sealed Bids", not the title. Walk
    backwards from the PIN to the last header, rejoin, then cut at the first
    " - " separator (which precedes the selection method)."""
    pin_idx = next((i for i, l in enumerate(lines) if "PIN#" in l), -1)
    if pin_idx == -1:
        return ""

    # Stop at the notice-type / category header. Do NOT stop at "any all-caps
    # line" — City Record titles are themselves all-caps, so that heuristic eats
    # the title and leaves you with the selection method.
    start = max(0, pin_idx - 4)
    for i in range(pin_idx, max(-1, pin_idx - 6), -1):
        if _HEADERS.match(lines[i]):
            start = i + 1
            break

    chunk = " ".join(lines[start:pin_idx + 1])
    chunk = chunk.split("PIN#")[0]
    title = chunk.split(" - ")[0]
    title = re.sub(r"[\s\-–—]+$", "", title).strip()
    return title if len(title) > 7 else ""


def fetch_todays_pdf(keywords: list[str]) -> tuple[list[dict], Status]:
    st = Status("City Record (today's PDF)")
    try:
        from pdfminer.high_level import extract_text
    except ImportError:
        st.ok = False
        st.note = "pdfminer.six not installed — same-day check skipped."
        return [], st

    try:
        u = requests.get(LATEST_PDF, timeout=20, headers=HEADERS)
        u.raise_for_status()
        pdf_url = u.text.strip().strip('"')
        pdf = requests.get(pdf_url, timeout=90, headers=HEADERS)
        pdf.raise_for_status()
        text = extract_text(BytesIO(pdf.content))
    except Exception as e:
        st.ok = False
        st.error = f"{type(e).__name__}: {e}"
        return [], st

    st.queries = 1

    # The PROCUREMENT section starts at the first PIN# (the table of contents
    # also contains the word PROCUREMENT, which is what tripped up the old
    # parser) and ends at the public-comment section.
    first_pin = text.find("PIN#")
    if first_pin == -1:
        st.note = "Today's edition has no procurement entries."
        return [], st
    start = max(0, first_pin - 2000)
    end = text.find("PUBLIC COMMENT ON", start)
    section = text[start: end if end != -1 else len(text)]

    # Each notice ends with a publication marker like "E jy14" / "jy8-14".
    blocks = re.split(r"\n\s*E?\s*[a-z]{1,2}\d{1,2}(?:-\d{1,2})?\s*\n", section)

    results, agency = [], "NYC Agency"
    for raw in blocks:
        raw = raw.strip()
        if len(raw) < 40 or any(b in raw for b in BOILERPLATE):
            continue
        if re.search(r"\.\s*\.\s*\.\s*\.\s*\d{3,4}", raw):     # TOC dot leaders
            continue

        lines = [l.strip() for l in raw.split("\n") if l.strip()]
        for line in lines[:6]:
            if (line.isupper() and 5 < len(line) < 80
                    and not line.startswith(("PIN", "AMT", "TO:", "BID", "FY"))):
                agency = line.title()
                break

        hits = [k for k in keywords if k.lower() in raw.lower()]
        if not hits:
            continue

        pin_m = re.search(r"PIN#\s*([\w\-/]+)", raw)
        if not pin_m:
            continue                                  # no PIN = not a solicitation
        pin = pin_m.group(1)

        title = _pdf_title(lines) or f"{agency} — {hits[0]}"

        upper = raw.upper()
        if "INTENT TO AWARD" in upper:
            rtype, ntype = INTENT, "Intent to Award"
        elif "SOLICITATION" in upper:
            rtype, ntype = SOLICITATION, "Solicitation"
        elif "AWARD" in upper:
            rtype, ntype = AWARD, "Award"
        else:
            rtype, ntype = OTHER, "Notice"

        due = re.search(r"Due\s+(\d{1,2}-\d{1,2}-\d{2,4})", raw)
        amt = re.search(r"AMT:\s*\$([\d,\.]+)", raw)
        vend = re.search(r"\bTO:\s*([^,\n]{5,80})", raw)
        mail = re.search(r"[\w\.\-]+@[\w\.\-]+\.\w+", raw)

        results.append({
            "id": stable_id("CRPDF", pin),
            "request_id": "",
            "title": title[:200],
            "agency": agency,
            "section": "Procurement",
            "category": "",
            "notice_type": ntype,
            "record_type": rtype,
            "selection_method": "",
            "mwbe_vehicle": bool(re.search(r"m/?wbe", raw, re.I)),
            "pin": pin,
            "amount": money(amt.group(1)) if amt else 0.0,
            "vendor": vend.group(1).strip() if vend else "",
            "due_date": norm_date(due.group(1)) if due else "",
            "issue_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "contact_name": "",
            "contact_email": mail.group(0) if mail else "",
            "contact_phone": "",
            "address": "",
            "source": "City Record (today's PDF)",
            "source_url": pdf_url,
            "matched_terms": hits,
            "raw_text": raw[:2000],
        })

    st.found = len(results)
    if not results:
        st.note = "No keyword matches in today's edition (normal on most days)."
    return results, st
