"""Harvest every open-access PDF in the field-map universe into `literature/`.

Stage I. Takes every work flagged `is_oa` with a resolvable OA URL (6,842 for
the biophoton pack), resolves each to an actual PDF, and downloads it into a
flat, sortable corpus in the build's literature directory, so the whole field
is greppable and indexable offline.

Resolution is layered, cheapest first:
  1. PDF links already in the cached OpenAlex record (best_oa_location, then
     every location, then the open_access.oa_url).
  2. Host-specific rewrites (arXiv abs->pdf, PMC->Europe PMC REST, Springer
     article->content/pdf, PLOS printable, MDPI /pdf, bioRxiv .full.pdf, ...),
     because a landing page is not a file.
  3. Unpaywall by DOI -- one cached call, catches works whose only OA URL is a
     bare doi.org redirect (1,452 in the biophoton pack). Unpaywall requires a
     contact address, so this layer runs only when OPENALEX_MAILTO is set.

Politeness is the binding constraint, not bandwidth: requests are serialised
per host with a per-host minimum interval, a shared UA carrying the project
mailto, exponential backoff on 429/503, and a circuit breaker that puts a host
into a timed cooldown after repeated refusals rather than retrying it into a
ban. Publishers that refuse an identified robot outright are recorded with
their status code and left for manual/institutional retrieval -- no browser
impersonation is attempted.

Every attempt lands in harvest_log.jsonl, so the run is fully resumable:
rerunning skips works that already have a file on disk and (unless
--retry-failed) works whose last attempt failed for a permanent reason.

Outputs under the build's literature directory (build.paths.literature):
  papers/<year>_<FirstAuthor>_<workid>.pdf   the corpus
  manifest.csv                               every OA work + outcome + checksum
  harvest_log.jsonl                          per-attempt audit trail

Usage:
  python harvest_oa_pdfs.py                 # full harvest, resumable
  python harvest_oa_pdfs.py --limit 50      # smoke test
  python harvest_oa_pdfs.py --retry-failed  # re-attempt soft failures
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import quote, urlparse

import httpx
import pandas as pd
from tqdm import tqdm
from unidecode import unidecode

import config as C

LIT = C.LIT
PAPERS = LIT / "papers"
LOG_PATH = LIT / "harvest_log.jsonl"
MANIFEST = LIT / "manifest.csv"
UNPAYWALL_CACHE = C.CACHE / "unpaywall"

MAX_PDF_BYTES = 120 * 1024 * 1024
MIN_PDF_BYTES = 2 * 1024            # anything smaller is an error page
WORKERS = 8
DEFAULT_HOST_INTERVAL = 1.0         # seconds between hits on the same host
HOST_INTERVAL = {
    "arxiv.org": 3.0,               # arXiv asks for >=3s between requests
    "export.arxiv.org": 3.0,
    "www.ebi.ac.uk": 0.5,
    "www.ncbi.nlm.nih.gov": 2.0,
    "pmc.ncbi.nlm.nih.gov": 2.0,
    "api.unpaywall.org": 0.2,
    "api.semanticscholar.org": 1.2,  # unauthenticated shared pool: ~1 rps
    "archive.org": 1.5,
    "web.archive.org": 1.5,
    # doi.org is a global redirect service and europepmc showed no throttling
    # under a burst; both are hit by a large share of works, so a long interval
    # here serialises the whole run behind them.
    "doi.org": 0.25,
    "europepmc.org": 0.6,
}
# Hosts that reliably serve a paywall/JS wall to a robot. Skipped up front so
# the run does not spend hours collecting 403s.
HOSTILE_HOSTS = {
    "www.researchgate.net", "www.academia.edu", "www.semanticscholar.org",
    "www.scribd.com",
}
# Indexing/abstract services -- these never host the file, so fetching them is
# pure latency. (PubMed abstract pages accounted for the single largest slice
# of wasted requests in the first trial run.)
NEVER_PDF_HOSTS = {
    "pubmed.ncbi.nlm.nih.gov", "doaj.org", "www.doaj.org",
    "gateway.webofknowledge.com", "www.webofscience.com", "www.scopus.com",
    "ui.adsabs.harvard.edu", "api.elsevier.com", "linkinghub.elsevier.com",
    "www.engineeringvillage.com", "search.crossref.org", "core.ac.uk",
}
MAX_ATTEMPTS_PER_WORK = 10
MAX_HTML_SCANS_PER_WORK = 3
MAX_HTML_BYTES = 400 * 1024
BLOCK_AFTER_403 = 12                # consecutive 403/429s before a host is cut
BLOCK_COOLDOWN = 600                # ...and for how long, in seconds
# Hosts whose 4xx/5xx means "this particular article isn't free here" rather
# than "stop hitting me" -- Europe PMC answers 403/500 per-article and shows no
# throttling under a burst, so counting those toward the breaker would take out
# our single best source of PMC full text.
SEMANTIC_REFUSAL_HOSTS = {"europepmc.org", "www.ebi.ac.uk"}

_host_lock: dict[str, threading.Lock] = defaultdict(threading.Lock)
_host_last: dict[str, float] = defaultdict(float)
_host_403: dict[str, int] = defaultdict(int)
_blocked: dict[str, float] = {}     # host -> monotonic time the block lifts
_ever_blocked: set[str] = set()
_state_lock = threading.Lock()
_log_lock = threading.Lock()


# --------------------------------------------------------------------------
# selection
# --------------------------------------------------------------------------
def load_communities(w: pd.DataFrame) -> pd.Series:
    """Cluster id per work, from whichever clustering export exists.

    The clustering stage is under active revision and its output file has been
    renamed more than once, so this only ever affects download *order* -- a
    missing file costs priority, not coverage.
    """
    for fname, col in (("work_communities_v2.csv", "community"),
                       ("work_communities_normalized.csv", "community_norm"),
                       ("work_communities.csv", "coupling_community")):
        path = C.EXPORTS / fname
        if not path.exists():
            continue
        df = pd.read_csv(path)
        for cand in (col, "community_norm", "community", "coupling_community"):
            if cand in df.columns:
                m = df.set_index("work_id")[cand]
                print(f"  cluster priority from {fname}:{cand}")
                return w["work_id"].map(m)
    print("  no clustering export found -- priority falls back to hop/citations")
    return pd.Series(pd.NA, index=w.index, dtype="Float64")


def oa_works() -> pd.DataFrame:
    """Every OA work with a URL, in download priority order.

    Priority puts the material closest to the seeds first, so an
    interrupted run still leaves the useful half on disk: seeds, then the
    1-hop neighbourhood, then the core cluster (community 0, when a
    clustering export exists), then the rest by citation count.
    """
    w = pd.read_parquet(C.EXPORTS / "works.parquet")
    w["community_norm"] = load_communities(w)
    oa = w[(w["is_oa"] == 1) & w["oa_url"].notna()].copy()
    oa["prio"] = (
        (oa["is_seed"] == 1).astype(int) * 1000
        + (oa["hop"] <= 1).astype(int) * 500
        + (oa["community_norm"] == 0).astype(int) * 250
    )
    oa = oa.sort_values(["prio", "cited_by_count"], ascending=False)
    return oa.reset_index(drop=True)


def cached_work(wid: str) -> dict | None:
    p = C.CACHE / "works" / f"{wid}.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except Exception:
        return None


def first_author(w: dict | None) -> str:
    if not w:
        return "Unknown"
    for a in (w.get("authorships") or []):
        name = ((a.get("author") or {}).get("display_name") or "").strip()
        if name:
            return name.split()[-1]        # surname
    return "Unknown"


def slug(s: str) -> str:
    s = re.sub(r"[^A-Za-z0-9]+", "-", unidecode(s or "")).strip("-")
    return s[:40] or "Unknown"


def dest_for(rec, w: dict | None) -> Path:
    year = int(rec.year) if pd.notna(rec.year) else 0
    ys = f"{year:04d}" if year else "0000"
    return PAPERS / f"{ys}_{slug(first_author(w))}_{rec.work_id}.pdf"


# --------------------------------------------------------------------------
# candidate URLs
# --------------------------------------------------------------------------
def _arxiv_pdf(url: str) -> str | None:
    m = re.search(r"arxiv\.org/(?:abs|pdf)/([^\s?#]+?)(?:\.pdf)?$", url, re.I)
    return f"https://arxiv.org/pdf/{m.group(1)}" if m else None


def _pmcid(url: str) -> str | None:
    m = re.search(r"(PMC\d+)", url or "", re.I)
    return m.group(1).upper() if m else None


def _pmc_pdf(url: str) -> list[str]:
    """PMC full text via Europe PMC, which serves it without NCBI's robot wall.

    NCBI's own /pdf/ endpoints return a 1.8 KB interstitial to a non-browser
    client, and the oa.fcgi `oa_package` hrefs 404 on both FTP and HTTPS, so
    Europe PMC's render endpoint is the only reliable route. The REST endpoint
    is kept as a secondary: it covers a slightly different subset.
    """
    pmcid = _pmcid(url)
    if not pmcid:
        return []
    return [
        f"https://europepmc.org/articles/{pmcid}?pdf=render",
        f"https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/fullTextPDF",
    ]


def rewrite(url: str) -> list[str]:
    """Landing page -> likely PDF endpoints for hosts we know."""
    if not url:
        return []
    host = urlparse(url).netloc.lower()
    out: list[str] = []

    if "arxiv.org" in host:
        if (u := _arxiv_pdf(url)):
            out.append(u)
    if "ncbi.nlm.nih.gov" in host or "europepmc.org" in host:
        out.extend(_pmc_pdf(url))
    if "link.springer.com" in host:
        m = re.search(r"/(?:article|chapter)/(10\.[^\s?#]+)", url)
        if m:
            out.append(f"https://link.springer.com/content/pdf/"
                       f"{m.group(1)}.pdf")
    if "journals.plos.org" in host:
        m = re.search(r"[?&]id=([^&]+)", url)
        if m:
            base = url.split("/article")[0]
            out.append(f"{base}/article/file?id={m.group(1)}"
                       f"&type=printable")
    if "frontiersin.org" in host:
        out.append(re.sub(r"/full/?$", "/pdf", url))
    if "mdpi.com" in host and not url.rstrip("/").endswith("pdf"):
        out.append(url.rstrip("/") + "/pdf")
    if "biorxiv.org" in host or "medrxiv.org" in host:
        out.append(re.sub(r"(\.full(\.pdf)?)?$", "", url.rstrip("/"))
                   + ".full.pdf")
    if "osf.io" in host and "/download" not in url:
        out.append(url.rstrip("/") + "/download")
    if "hal." in host and not url.rstrip("/").endswith("document"):
        out.append(url.rstrip("/") + "/document")
    if "jstage.jst.go.jp" in host:
        out.append(re.sub(r"/_article.*$", "/_pdf", url))
    if "iopscience.iop.org" in host:
        out.append(re.sub(r"/meta/?$", "", url.rstrip("/")) + "/pdf")
    if "tandfonline.com" in host:
        out.append(url.replace("/doi/abs/", "/doi/pdf/")
                      .replace("/doi/full/", "/doi/pdf/"))
    if "cambridge.org" in host and "/core/" in url:
        out.append(url.rstrip("/") + "/core-reader")
    return out


def candidates(rec, w: dict | None) -> list[str]:
    """Ordered, de-duplicated PDF candidates for one work."""
    urls: list[str] = []

    def add(u: str | None) -> None:
        if u and u.startswith("http") and u not in urls:
            urls.append(u)

    locs: list[dict] = []
    if w:
        for key in ("best_oa_location", "primary_location"):
            if (loc := w.get(key)):
                locs.append(loc)
        locs.extend(w.get("locations") or [])

    # direct pdf_urls first -- these are files, not pages
    for loc in locs:
        add(loc.get("pdf_url"))
    # then rewrites of every landing page we know how to turn into a file
    for loc in locs:
        for u in rewrite(loc.get("landing_page_url") or ""):
            add(u)
    for loc in locs:
        for u in rewrite(loc.get("pdf_url") or ""):
            add(u)
    oa_url = str(rec.oa_url) if pd.notna(rec.oa_url) else ""
    for u in rewrite(oa_url):
        add(u)
    # landing pages last: some of them are the PDF, content-type will tell us
    for loc in locs:
        add(loc.get("landing_page_url"))
    add(oa_url)

    return [u for u in urls if urlparse(u).netloc.lower() not in HOSTILE_HOSTS]


def unpaywall_pdf(client: httpx.Client, doi: str) -> str | None:
    """Cached Unpaywall lookup -- the fallback for bare doi.org OA URLs."""
    if not doi or not C.MAILTO:   # Unpaywall requires a contact address
        return None
    doi = doi.replace("https://doi.org/", "").strip().lower()
    if not doi.startswith("10."):
        return None
    UNPAYWALL_CACHE.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha1(doi.encode()).hexdigest()
    cp = UNPAYWALL_CACHE / f"{key}.json"
    if cp.exists():
        try:
            data = json.loads(cp.read_text())
        except Exception:
            data = {}
    else:
        try:
            throttle("api.unpaywall.org")
            r = client.get(f"https://api.unpaywall.org/v2/{quote(doi)}",
                           params={"email": C.MAILTO}, timeout=30.0)
            data = r.json() if r.status_code == 200 else {}
        except Exception:
            data = {}
        cp.write_text(json.dumps(data))
    best = (data or {}).get("best_oa_location") or {}
    urls = [best.get("url_for_pdf"), best.get("url")]
    for loc in ((data or {}).get("oa_locations") or []):
        urls.append(loc.get("url_for_pdf"))
    for u in urls:
        if u and u.startswith("http"):
            return u
    return None


# --------------------------------------------------------------------------
# polite fetching
# --------------------------------------------------------------------------
def throttle(host: str) -> None:
    """Serialise same-host requests with a per-host minimum gap."""
    interval = HOST_INTERVAL.get(host, DEFAULT_HOST_INTERVAL)
    with _host_lock[host]:
        wait = _host_last[host] + interval - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _host_last[host] = time.monotonic()


def note_refusal(host: str) -> None:
    """Back off a host that keeps refusing -- but only for a cooldown.

    A permanent cut would let one burst of rate limiting lose a host for the
    whole run, which is exactly what happened to Europe PMC (the best source
    for PMC full text) in an earlier trial.
    """
    if host in SEMANTIC_REFUSAL_HOSTS:
        return
    with _state_lock:
        _host_403[host] += 1
        if _host_403[host] >= BLOCK_AFTER_403:
            _blocked[host] = time.monotonic() + BLOCK_COOLDOWN
            _ever_blocked.add(host)
            _host_403[host] = 0


def note_success(host: str) -> None:
    with _state_lock:
        _host_403[host] = 0


def is_blocked(host: str) -> bool:
    with _state_lock:
        until = _blocked.get(host)
        if until is None:
            return False
        if time.monotonic() >= until:
            del _blocked[host]
            return False
        return True


class Fetched:
    """Outcome of one GET: a PDF, a landing page to mine, or nothing."""

    __slots__ = ("kind", "data", "html", "final_url", "reason")

    def __init__(self, kind: str, reason: str, data: bytes = b"",
                 html: str = "", final_url: str = ""):
        self.kind = kind          # "pdf" | "html" | "none"
        self.reason = reason
        self.data = data
        self.html = html
        self.final_url = final_url


def fetch(client: httpx.Client, url: str) -> Fetched:
    """GET a URL, streaming, and classify what came back.

    HTML is kept (capped) rather than discarded: a landing page usually
    advertises its own PDF via <meta name="citation_pdf_url">, which is how
    most repository and OJS-based journal hits are actually resolved.
    """
    host = urlparse(url).netloc.lower()
    if is_blocked(host):
        return Fetched("none", "host-cooling-off")
    for attempt in range(3):
        throttle(host)
        try:
            with client.stream("GET", url) as r:
                final = str(r.url)
                if r.status_code in (429, 503):
                    note_refusal(host)
                    time.sleep(2 ** attempt * 5)
                    continue
                if r.status_code in (401, 403):
                    note_refusal(host)
                    return Fetched("none", f"http-{r.status_code}")
                if r.status_code != 200:
                    return Fetched("none", f"http-{r.status_code}")
                ctype = (r.headers.get("content-type") or "").lower()
                if int(r.headers.get("content-length") or 0) > MAX_PDF_BYTES:
                    return Fetched("none", "too-large")

                if "html" in ctype or "xml" in ctype:
                    buf = bytearray()
                    for chunk in r.iter_bytes(65536):
                        buf.extend(chunk)
                        if len(buf) > MAX_HTML_BYTES:
                            break
                    note_success(host)
                    return Fetched("html", "landing-page",
                                   html=bytes(buf).decode("utf-8", "ignore"),
                                   final_url=final)

                buf = bytearray()
                for chunk in r.iter_bytes(65536):
                    buf.extend(chunk)
                    # magic bytes are authoritative: some hosts mislabel a real
                    # PDF, and some serve HTML under application/pdf
                    if len(buf) >= 5 and bytes(buf[:5]) != b"%PDF-":
                        head = bytes(buf[:400]).decode("utf-8", "ignore")
                        if "<html" in head.lower() or "<!doct" in head.lower():
                            for chunk in r.iter_bytes(65536):
                                buf.extend(chunk)
                                if len(buf) > MAX_HTML_BYTES:
                                    break
                            return Fetched(
                                "html", "mislabelled-html",
                                html=bytes(buf).decode("utf-8", "ignore"),
                                final_url=final)
                        return Fetched("none", "not-pdf")
                    if len(buf) > MAX_PDF_BYTES:
                        return Fetched("none", "too-large")
            data = bytes(buf)
            if len(data) < MIN_PDF_BYTES:
                return Fetched("none", "too-small")
            note_success(host)
            return Fetched("pdf", "ok", data=data, final_url=final)
        except httpx.HTTPError as e:
            if attempt == 2:
                return Fetched("none", f"error-{type(e).__name__}")
            time.sleep(2 ** attempt)
    return Fetched("none", "retries-exhausted")


META_PDF_RE = re.compile(
    r"""<meta[^>]+name=["']citation_pdf_url["'][^>]+content=["']([^"']+)["']""",
    re.I)
META_PDF_RE2 = re.compile(
    r"""<meta[^>]+content=["']([^"']+)["'][^>]+name=["']citation_pdf_url["']""",
    re.I)
PDF_HREF_RE = re.compile(r"""href=["']([^"']+?\.pdf(?:\?[^"']*)?)["']""", re.I)


def mine_html(html: str, base_url: str) -> list[str]:
    """Pull PDF links a landing page declares about itself."""
    out: list[str] = []

    def absolutise(u: str) -> str:
        if u.startswith("//"):
            return "https:" + u
        if u.startswith("http"):
            return u
        p = urlparse(base_url)
        if u.startswith("/"):
            return f"{p.scheme}://{p.netloc}{u}"
        return f"{p.scheme}://{p.netloc}/{u.lstrip('./')}"

    for rx in (META_PDF_RE, META_PDF_RE2):
        for m in rx.finditer(html):
            u = absolutise(m.group(1).replace("&amp;", "&"))
            if u not in out:
                out.append(u)
    if out:
        return out
    # last resort: same-host links that end in .pdf (DSpace/EPrints bitstreams)
    base_host = urlparse(base_url).netloc.lower()
    for m in PDF_HREF_RE.finditer(html):
        u = absolutise(m.group(1).replace("&amp;", "&"))
        if urlparse(u).netloc.lower() == base_host and u not in out:
            out.append(u)
        if len(out) >= 2:
            break
    return out


def s2_pdf(client: httpx.Client, doi: str) -> str | None:
    """Semantic Scholar's openAccessPdf -- an aggregator that carries OA
    copies under publisher agreements, so it legitimately resolves works
    whose own landing pages dead-end. Cached; unauthenticated tier."""
    doi = (doi or "").strip().lower()
    if not doi.startswith("10."):
        return None
    cache = C.CACHE / "s2"
    cache.mkdir(parents=True, exist_ok=True)
    cp = cache / (hashlib.sha1(doi.encode()).hexdigest() + ".json")
    if cp.exists():
        try:
            data = json.loads(cp.read_text())
        except Exception:
            data = {}
    else:
        throttle("api.semanticscholar.org")
        try:
            r = client.get(
                f"https://api.semanticscholar.org/graph/v1/paper/DOI:"
                f"{quote(doi)}", params={"fields": "openAccessPdf"},
                timeout=30.0)
            data = r.json() if r.status_code == 200 else {}
        except Exception:
            data = {}
        cp.write_text(json.dumps(data))
    u = ((data or {}).get("openAccessPdf") or {}).get("url")
    return u if u and u.startswith("http") else None


def wayback_pdf(client: httpx.Client, url: str) -> str | None:
    """Internet Archive snapshot for a dead link (404/410 bucket)."""
    if not url or not url.startswith("http"):
        return None
    throttle("archive.org")
    try:
        r = client.get("https://archive.org/wayback/available",
                       params={"url": url}, timeout=30.0)
        snap = (((r.json() or {}).get("archived_snapshots") or {})
                .get("closest") or {})
        u = snap.get("url")
        if u and snap.get("available"):
            # id_ variant serves the original bytes without the toolbar
            return re.sub(r"(/web/\d+)/", r"\1id_/", u.replace("http://", "https://", 1))
    except Exception:
        pass
    return None


def pmc_urls(queue: list[str], w: dict | None) -> list[str]:
    """Europe PMC render URLs for any PMCID mentioned anywhere in this work."""
    blobs = list(queue)
    for loc in ((w or {}).get("locations") or []):
        blobs += [loc.get("landing_page_url") or "", loc.get("pdf_url") or ""]
    for b in blobs:
        if (urls := _pmc_pdf(b)):
            return urls
    return []


# --------------------------------------------------------------------------
# per-work worker
# --------------------------------------------------------------------------
def log_attempt(row: dict) -> None:
    with _log_lock:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")


def handle(rec, client: httpx.Client, done: dict) -> dict:
    wid = rec.work_id
    w = cached_work(wid)
    dest = dest_for(rec, w)
    doi = (str(rec.doi) if pd.notna(rec.doi) else "").replace(
        "https://doi.org/", "")

    if dest.exists() and dest.stat().st_size >= MIN_PDF_BYTES:
        return {"work_id": wid, "status": "have", "file": dest.name,
                "bytes": dest.stat().st_size, "url": done.get(wid, ""),
                "reason": "already-on-disk"}

    # a few OA PDFs were already pulled by the contacts stage -- reuse them
    cached_pdf = C.CACHE / "pdfs" / f"{wid}.pdf"
    if cached_pdf.exists() and cached_pdf.stat().st_size >= MIN_PDF_BYTES:
        head = cached_pdf.read_bytes()[:5]
        if head == b"%PDF-":
            dest.write_bytes(cached_pdf.read_bytes())
            return {"work_id": wid, "status": "ok", "file": dest.name,
                    "bytes": dest.stat().st_size, "url": "cache://pdfs",
                    "reason": "from-pipeline-cache"}

    def save(data: bytes, url: str, why: str) -> dict:
        dest.write_bytes(data)
        return {"work_id": wid, "status": "ok", "file": dest.name,
                "bytes": len(data), "url": url, "reason": why}

    tried: list[str] = []
    queue = candidates(rec, w)
    if (u := unpaywall_pdf(client, doi)) and u not in queue:
        queue.append(u)
    if (u := s2_pdf(client, doi)) and u not in queue:
        queue.append(u)

    # PMC full text is fetched from Europe PMC, ahead of everything else: it
    # is a clean direct PDF where the publisher copy is often walled.
    queue[:0] = [u for u in pmc_urls(queue, w) if u not in queue]

    seen: set[str] = set()
    dead_urls: list[str] = []      # direct candidates that 404/410ed
    html_scans = 0
    attempts = 0
    while queue and attempts < MAX_ATTEMPTS_PER_WORK:
        url = queue.pop(0)
        if url in seen:
            continue
        seen.add(url)
        host = urlparse(url).netloc.lower()
        if host in NEVER_PDF_HOSTS or host in HOSTILE_HOSTS:
            continue
        attempts += 1
        res = fetch(client, url)
        tried.append(f"{host}:{res.reason}")
        if res.reason in ("http-404", "http-410"):
            dead_urls.append(url)
        if res.kind == "pdf":
            return save(res.data, url, "ok")
        if res.kind == "html" and html_scans < MAX_HTML_SCANS_PER_WORK:
            html_scans += 1
            # the page's own declared PDF first, then anything our host rules
            # can make of where we actually landed after redirects
            found = [u for u in mine_html(res.html, res.final_url)
                     if u not in seen]
            found += [u for u in rewrite(res.final_url) if u not in seen]
            queue[:0] = found[:3]

    # last resort for dead links: the Internet Archive's copy of the first
    # direct-PDF candidates that 404ed on the live web
    for orig in dead_urls[:2]:
        if (au := wayback_pdf(client, orig)):
            res = fetch(client, au)
            tried.append(f"wayback:{res.reason}")
            if res.kind == "pdf":
                return save(res.data, au, "wayback")

    return {"work_id": wid, "status": "failed", "file": "", "bytes": 0,
            "url": (candidates(rec, w) or [""])[0],
            "reason": ";".join(tried[:8]) or "no-candidates"}


# --------------------------------------------------------------------------
def load_log() -> dict[str, dict]:
    seen: dict[str, dict] = {}
    if LOG_PATH.exists():
        with open(LOG_PATH, encoding="utf-8") as f:
            for line in f:
                try:
                    r = json.loads(line)
                except Exception:
                    continue
                seen[r["work_id"]] = r
    return seen


def work_license(wid: str) -> str:
    """Best-known licence from the cached OpenAlex record.

    This is what decides whether a copy may be *redistributed* (CC-*) or
    merely read at source (publisher-specific free-to-read) -- the manifest
    carries it so any hosting decision can be made per file.
    """
    w = cached_work(wid)
    if not w:
        return ""
    locs = [w.get("best_oa_location"), w.get("primary_location")]
    locs += list(w.get("locations") or [])
    for loc in locs:
        if loc and loc.get("license"):
            return str(loc["license"])
    return ""


def write_manifest(oa: pd.DataFrame, results: dict[str, dict]) -> None:
    rows = []
    for rec in oa.itertuples():
        r = results.get(rec.work_id, {})
        fn = r.get("file", "")
        path = PAPERS / fn if fn else None
        sha = ""
        if path and path.exists():
            h = hashlib.sha256()
            with open(path, "rb") as f:
                for chunk in iter(lambda: f.read(1 << 20), b""):
                    h.update(chunk)
            sha = h.hexdigest()
        rows.append({
            "work_id": rec.work_id,
            "doi": (str(rec.doi) if pd.notna(rec.doi) else "").replace(
                "https://doi.org/", ""),
            "title": (str(rec.title) if pd.notna(rec.title) else "")[:300],
            "year": int(rec.year) if pd.notna(rec.year) else "",
            "type": rec.type,
            "cited_by_count": rec.cited_by_count,
            "oa_status": rec.oa_status,
            "license": work_license(rec.work_id),
            "community": (int(rec.community_norm)
                          if pd.notna(rec.community_norm) else ""),
            "hop": rec.hop,
            "is_seed": rec.is_seed,
            "status": r.get("status", "pending"),
            "file": f"papers/{fn}" if fn else "",
            "bytes": r.get("bytes", 0),
            "sha256": sha,
            "source_url": r.get("url", ""),
            "reason": r.get("reason", ""),
        })
    with open(MANIFEST, "w", newline="", encoding="utf-8") as f:
        wr = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        wr.writeheader()
        wr.writerows(rows)


PERMANENT = ("host-blocked", "http-404", "http-410", "no-candidates")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--retry-failed", action="store_true")
    ap.add_argument("--workers", type=int, default=WORKERS)
    ap.add_argument("--manifest-only", action="store_true",
                    help="rewrite manifest.csv from the log, no downloads")
    args = ap.parse_args()

    PAPERS.mkdir(parents=True, exist_ok=True)
    oa = oa_works()
    prior = load_log()
    if args.manifest_only:
        write_manifest(oa, prior)
        print(f"manifest rewritten from log: {MANIFEST}")
        return

    todo = []
    for rec in oa.itertuples():
        p = prior.get(rec.work_id)
        if p and p.get("status") in ("ok", "have"):
            continue
        if p and p.get("status") == "failed" and not args.retry_failed:
            if any(k in (p.get("reason") or "") for k in PERMANENT):
                continue
            continue
        todo.append(rec)
    if args.limit:
        todo = todo[:args.limit]

    print(f"OA works: {len(oa)}   already harvested: "
          f"{sum(1 for v in prior.values() if v.get('status') in ('ok','have'))}"
          f"   to attempt: {len(todo)}")

    client = httpx.Client(
        timeout=httpx.Timeout(60.0, connect=20.0), follow_redirects=True,
        headers={"User-Agent": C.USER_AGENT + (
                     f" (mailto:{C.MAILTO})" if C.MAILTO else ""),
                 "Accept": "application/pdf,*/*"})

    results = dict(prior)
    n_ok = n_fail = 0
    try:
        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            futs = {ex.submit(handle, rec, client, {}): rec for rec in todo}
            with tqdm(total=len(futs), desc="pdfs") as bar:
                for fut in as_completed(futs):
                    try:
                        row = fut.result()
                    except Exception as e:
                        rec = futs[fut]
                        row = {"work_id": rec.work_id, "status": "failed",
                               "file": "", "bytes": 0, "url": "",
                               "reason": f"worker-{type(e).__name__}"}
                    results[row["work_id"]] = row
                    log_attempt(row)
                    n_ok += row["status"] in ("ok", "have")
                    n_fail += row["status"] == "failed"
                    bar.update(1)
                    bar.set_postfix(ok=n_ok, fail=n_fail,
                                    cooling=len(_blocked))
    except KeyboardInterrupt:
        print("\ninterrupted -- writing manifest for what landed")
    finally:
        client.close()

    write_manifest(oa, results)
    have = sum(1 for v in results.values() if v.get("status") in ("ok", "have"))
    size = sum((PAPERS / v["file"]).stat().st_size
               for v in results.values()
               if v.get("file") and (PAPERS / v["file"]).exists())
    print("=== harvest_oa_pdfs ===")
    print(f"  OA works in universe : {len(oa)}")
    print(f"  PDFs on disk         : {have} ({have / len(oa):.1%})")
    print(f"  corpus size          : {size / 1e9:.2f} GB")
    if _ever_blocked:
        print(f"  hosts that rate-limited us: "
              f"{', '.join(sorted(_ever_blocked))}")
    print(f"  manifest             : {MANIFEST}")


if __name__ == "__main__":
    main()
