"""Thin OpenAlex client: polite pool, cursor paging, retry, disk cache.

Every entity fetched is cached to one JSON file keyed by its OpenAlex id, so a
rerun costs zero network and the harvest is fully resumable (spec §2).
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

import config as C


def oa_short_id(oa_id: str) -> str:
    """'https://openalex.org/W123' or 'W123' -> 'W123'."""
    if not oa_id:
        return oa_id
    return oa_id.rstrip("/").rsplit("/", 1)[-1]


def _redact(text: str) -> str:
    """Strip the API key from anything that may reach a log or traceback:
    httpx puts the full request URL, query string included, in its errors."""
    return text.replace(C.API_KEY, "<OPENALEX_API_KEY>") if C.API_KEY else text


def _check(r: httpx.Response) -> None:
    """raise_for_status, with the key redacted from the message."""
    try:
        r.raise_for_status()
    except httpx.HTTPStatusError as e:
        raise httpx.HTTPStatusError(_redact(str(e)), request=e.request,
                                    response=e.response) from None


def _cache_path(kind: str, short_id: str) -> Path:
    sub = C.CACHE / kind
    sub.mkdir(parents=True, exist_ok=True)
    return sub / f"{short_id}.json"


class OpenAlex:
    def __init__(self) -> None:
        self._client = httpx.Client(
            timeout=C.TIMEOUT,
            headers={"User-Agent": C.USER_AGENT + (
                f" (mailto:{C.MAILTO})" if C.MAILTO else "")},
            follow_redirects=True,
        )
        self.n_requests = 0

    def close(self) -> None:
        self._client.close()

    # -- low-level GET with retry + polite pacing --------------------------
    @retry(
        retry=retry_if_exception_type(
            (httpx.TransportError, httpx.HTTPStatusError)
        ),
        wait=wait_exponential(multiplier=1, min=2, max=C.RETRY_MAX_WAIT),
        stop=stop_after_attempt(C.MAX_RETRIES),
        reraise=True,
    )
    def _get(self, url: str, params: dict[str, Any]) -> dict[str, Any]:
        params = dict(params)
        if C.MAILTO:
            params["mailto"] = C.MAILTO
        if C.API_KEY:
            params["api_key"] = C.API_KEY
        try:
            r = self._client.get(url, params=params)
        except httpx.TransportError as e:
            raise type(e)(_redact(str(e))) from None
        self.n_requests += 1
        # 429/5xx -> back off (honor Retry-After) and raise for tenacity;
        # 404 -> return so the caller can handle it.
        if r.status_code == 429 or r.status_code >= 500:
            retry_after = r.headers.get("Retry-After")
            if retry_after:
                try:
                    time.sleep(min(float(retry_after), C.RETRY_MAX_WAIT))
                except ValueError:
                    time.sleep(5)
            _check(r)
        time.sleep(C.SLEEP_BETWEEN)
        return r

    # -- cached single-entity fetch by id ----------------------------------
    def get_entity(self, kind: str, oa_id: str, select: str | None = None
                   ) -> dict[str, Any] | None:
        """kind in {'works','authors','institutions'}. Cached by short id."""
        sid = oa_short_id(oa_id)
        cp = _cache_path(kind, sid)
        if cp.exists():
            return json.loads(cp.read_text())
        params: dict[str, Any] = {}
        if select:
            params["select"] = select
        url = f"{C.OPENALEX_BASE}/{kind}/{sid}"
        r = self._get(url, params)
        if r.status_code == 404:
            cp.write_text(json.dumps(None))
            return None
        _check(r)
        obj = r.json()
        cp.write_text(json.dumps(obj))
        return obj

    def get_cached(self, kind: str, oa_id: str) -> dict[str, Any] | None:
        """Return a cached entity without hitting the network (or None)."""
        cp = _cache_path(kind, oa_short_id(oa_id))
        if cp.exists():
            return json.loads(cp.read_text())
        return None

    # -- filtered listing with cursor paging -------------------------------
    def paged(self, kind: str, filter_str: str, select: str | None = None,
              sort: str | None = None, cap: int | None = None,
              ) -> Iterator[dict[str, Any]]:
        """Yield every result for a filter, cursor-paginated. Not per-item
        cached (list queries are transient); callers cache the entities."""
        cursor = "*"
        yielded = 0
        while cursor:
            params: dict[str, Any] = {
                "filter": filter_str,
                "per-page": C.PER_PAGE,
                "cursor": cursor,
            }
            if select:
                params["select"] = select
            if sort:
                params["sort"] = sort
            r = self._get(f"{C.OPENALEX_BASE}/{kind}", params)
            _check(r)
            payload = r.json()
            for item in payload.get("results", []):
                yield item
                yielded += 1
                if cap is not None and yielded >= cap:
                    return
            cursor = payload.get("meta", {}).get("next_cursor")
            if not payload.get("results"):
                break

    def count(self, kind: str, filter_str: str) -> int:
        params = {"filter": filter_str, "per-page": 1}
        r = self._get(f"{C.OPENALEX_BASE}/{kind}", params)
        _check(r)
        return r.json().get("meta", {}).get("count", 0)

    # -- batched entity fetch by id, caching each entity -------------------
    def entities_by_ids(self, kind: str, ids: Iterable[str],
                        select: str | None = None,
                        progress: Callable[[int], None] | None = None,
                        ) -> dict[str, dict[str, Any]]:
        """Fetch many entities of `kind` by OpenAlex id, using cache; batch the
        uncached ones via filter=openalex_id:a|b|... (50 per request).
        Returns {short_id: entity}. Not-found ids are cached as null."""
        ids = [oa_short_id(i) for i in ids]
        out: dict[str, dict[str, Any]] = {}
        missing: list[str] = []
        for sid in ids:
            cached = self.get_cached(kind, sid)
            if cached is not None:
                out[sid] = cached
            elif _cache_path(kind, sid).exists():
                pass  # cached as null (404) — skip
            else:
                missing.append(sid)
        done = len(out)
        if progress:
            progress(done)
        for i in range(0, len(missing), 50):
            batch = missing[i:i + 50]
            filt = "openalex_id:" + "|".join(batch)
            got = set()
            for e in self.paged(kind, filt, select=select):
                sid = oa_short_id(e["id"])
                _cache_path(kind, sid).write_text(json.dumps(e))
                out[sid] = e
                got.add(sid)
            for sid in batch:
                if sid not in got and not _cache_path(kind, sid).exists():
                    _cache_path(kind, sid).write_text(json.dumps(None))
            done += len(batch)
            if progress:
                progress(done)
        return out

    def works_by_ids(self, ids: Iterable[str], select: str | None = None,
                     progress: Callable[[int], None] | None = None,
                     ) -> dict[str, dict[str, Any]]:
        """Batched works fetch (see entities_by_ids)."""
        return self.entities_by_ids("works", ids, select or C.WORK_SELECT,
                                    progress)


def title_filter(title: str) -> str:
    """Build a title.search filter value.

    httpx URL-encodes params for us, so return raw text. Strip commas and
    pipes, which are AND/OR operators inside an OpenAlex filter value, and
    trim the tail (title.search is token-based, a long tail adds no signal).
    """
    t = title.replace("\n", " ").replace(",", " ").replace("|", " ")
    t = " ".join(t.split())
    return t[:250]
