from __future__ import annotations

"""Runs 3 Tavily queries about the user and stores deduplicated results."""

import json
import logging
import os
import time
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from tavily import TavilyClient

logger = logging.getLogger(__name__)

CACHE_PATH = Path("output/tavily_raw.json")
CACHE_MAX_AGE_HOURS = 24
_MAX_RESULTS_PER_QUERY = 5
_CONTENT_MAX_CHARS = 500

def _load_env() -> dict[str, str | None]:
    """Load and validate required env vars.

    Returns dict with keys: TAVILY_API_KEY, USER_NAME, USER_EMAIL.
    Unlike the original, does NOT raise if TAVILY_API_KEY is missing
    — that's handled gracefully by returning empty results.
    USER_NAME and USER_EMAIL are optional but nice to have.
    """
    load_dotenv()
    config: dict[str, str | None] = {
        "TAVILY_API_KEY": os.environ.get("TAVILY_API_KEY"),
        "USER_NAME": os.environ.get("USER_NAME"),
        "USER_EMAIL": os.environ.get("USER_EMAIL"),
    }
    return config


def _normalize_name(raw: str) -> str:
    """Replace underscores with spaces in USER_NAME."""
    return raw.replace("_", " ")


def _build_queries(user_name: str, user_email: str) -> list[tuple[str, str]]:
    """Return list of (query_key, query_string) tuples for the three searches."""
    domain = user_email.split("@")[1]
    return [
        ("q1", user_name),
        ("q2", f"{user_name} {domain}"),
        ("q3", f"{user_name} github OR linkedin OR twitter"),
    ]


def _run_query(client: TavilyClient, query_key: str, query: str) -> list[dict[str, Any]]:
    """Run a single Tavily query. Returns list of normalized result dicts.

    Logs a warning and returns [] on any exception — never raises.
    """
    try:
        response = client.search(
            query=query,
            search_depth="basic",
            max_results=_MAX_RESULTS_PER_QUERY,
        )
        raw_results: list[dict[str, Any]] = response.get("results", [])
        return [
            {
                "url": r.get("url", ""),
                "title": r.get("title", ""),
                "content": (r.get("content") or "")[:_CONTENT_MAX_CHARS],
                "score": float(r.get("score", 0.0)),
            }
            for r in raw_results
            if r.get("url")
        ]
    except Exception as exc:  # noqa: BLE001
        logger.warning("Tavily query %s (%r) failed: %s", query_key, query, exc)
        return []


def _deduplicate(
    query_results: dict[str, list[dict[str, Any]]]
) -> list[dict[str, Any]]:
    """Merge results from all queries, keeping the highest-score entry per URL."""
    seen: dict[str, dict[str, Any]] = {}
    for results in query_results.values():
        for result in results:
            url = result["url"]
            if url not in seen or result["score"] > seen[url]["score"]:
                seen[url] = result
    return list(seen.values())


def _is_cache_fresh(cache: dict[str, Any]) -> bool:
    """Return True if the cache was written within the TTL window."""
    fetched_at = cache.get("fetched_at", 0)
    return (time.time() - fetched_at) < (CACHE_MAX_AGE_HOURS * 3600)


def _load_cache() -> dict[str, Any] | None:
    """Load cached JSON from disk. Returns None if missing or corrupt."""
    if not CACHE_PATH.exists():
        return None
    try:
        return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Cache file unreadable (%s), will re-fetch.", exc)
        return None


def _save_cache(
    results: list[dict[str, Any]],
    query_counts: dict[str, int],
    user_name: str,
    user_email: str,
) -> None:
    """Write results and metadata to the cache file atomically."""
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "fetched_at": int(time.time()),
        "user_name": user_name,
        "user_email": user_email,
        "query_counts": query_counts,
        "results": results,
    }
    tmp_path = CACHE_PATH.with_suffix(".tmp")
    tmp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp_path.replace(CACHE_PATH)
    logger.debug("Tavily results saved to %s", CACHE_PATH)


def fetch_tavily_data(force_refresh: bool = False) -> list[dict[str, Any]]:
    """Fetch public Tavily results for the user. Returns deduplicated result dicts.

    Uses a 24h on-disk cache at output/tavily_raw.json.
    Pass force_refresh=True to bypass the cache (e.g. from --no-cache flag).
    Returns an empty list and never raises if all queries fail or return nothing.
    If TAVILY_API_KEY is not set, returns empty list with a log message.
    """
    config = _load_env()

    # Gracefully handle missing API key (free/local mode)
    api_key = config.get("TAVILY_API_KEY")
    if not api_key:
        logger.info("TAVILY_API_KEY not set — skipping Tavily fetch (free/local mode).")
        return []

    user_name_raw = config.get("USER_NAME") or "User"
    user_name = _normalize_name(user_name_raw)
    user_email = config.get("USER_EMAIL") or ""

    if not force_refresh:
        cached = _load_cache()
        if cached and _is_cache_fresh(cached):
            logger.info("Using cached Tavily results from %s.", CACHE_PATH)
            return cached.get("results", [])

    logger.info("Fetching Tavily data for %r.", user_name)
    client = TavilyClient(api_key=api_key)
    queries = _build_queries(user_name, user_email)

    query_results: dict[str, list[dict[str, Any]]] = {}
    for key, query in queries:
        logger.info("Running Tavily query %s: %r", key, query)
        query_results[key] = _run_query(client, key, query)

    results = _deduplicate(query_results)
    query_counts = {key: len(results_) for key, results_ in query_results.items()}

    if not results:
        logger.warning(
            "Tavily returned 0 results for %r across all queries. "
            "Check TAVILY_API_KEY and USER_NAME.",
            user_name,
        )
    else:
        logger.info("Tavily fetch complete: %d unique results.", len(results))

    _save_cache(results, query_counts, user_name, user_email)
    return results


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    fetched = fetch_tavily_data()
    print(f"Fetched {len(fetched)} results")
    for r in fetched[:3]:
        print(f"  {r['score']:.2f}  {r['title']}  —  {r['url']}")
