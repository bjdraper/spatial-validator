"""Cache-first PubMed literature retrieval (NCBI E-utilities).

Design (option B): live search with a persistent on-disk cache.
  * First time a query is seen -> live esearch + esummary + efetch against
    PubMed, results written to the cache.
  * Every subsequent run with the same (normalized) query -> served from cache:
    fast, offline, and reproducible. Commit the cache dir to freeze a demo /
    benchmark snapshot.
  * `source: cache_only` (or no network) -> cache hits only, misses degrade
    gracefully to "no literature" instead of erroring.

Standalone on purpose: uses only the Python stdlib (urllib), so the deployed
agent has no dependency on this session's PubMed MCP and runs anywhere.

A date ceiling (`as_of`) is passed to esearch as `maxdate`, so "live" means
"PubMed as of <date>" — the lever that keeps a live source reproducible.
"""
import hashlib
import json
import os
import re
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

_EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
_STOP = {  # dropped when normalizing a query into a cache key
    "the", "a", "an", "of", "in", "for", "and", "or", "to", "is", "are",
    "marker", "markers", "gene", "genes", "cell", "celltype", "cells", "type",
    "types", "gold", "standard", "specific", "expression", "expressed",
}


def _norm_key(query, as_of, top_k):
    """Stable cache key: lowercase, drop punctuation + filler words, sort tokens.

    Similar phrasings ("RORB layer 4 marker" vs "marker gene RORB layer4")
    collapse to the same key, so the warm cache actually gets hit at demo time.
    """
    toks = re.findall(r"[a-z0-9]+", query.lower())
    toks = sorted({t for t in toks if t not in _STOP})
    basis = "|".join(toks) + f"|as_of={as_of}|k={top_k}"
    return hashlib.sha1(basis.encode()).hexdigest()[:16]


def _lit_cfg(cfg):
    lit = dict(cfg.get("literature") or {})
    lit.setdefault("enabled", False)
    lit.setdefault("source", "pubmed")        # pubmed | cache_only | none
    lit.setdefault("top_k", 4)
    lit.setdefault("as_of", "")
    lit.setdefault("cache_dir", "data/litcache")
    lit.setdefault("ncbi_api_key_env", "NCBI_API_KEY")
    return lit


def _get_json(path, params):
    url = f"{_EUTILS}/{path}?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=12) as r:
        return json.load(r)


def _get_text(path, params):
    url = f"{_EUTILS}/{path}?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=12) as r:
        return r.read().decode("utf-8", "replace")


def _api_params(lit):
    key = os.environ.get(lit["ncbi_api_key_env"], "")
    return {"api_key": key} if key else {}


def _throttle(lit):
    # 3 req/s anonymous, 10 req/s with a key.
    time.sleep(0.11 if os.environ.get(lit["ncbi_api_key_env"]) else 0.34)


def _abstract_snippet(abstract, query):
    """First abstract sentence mentioning a query token, else the lead sentence."""
    if not abstract:
        return ""
    sents = re.split(r"(?<=[.!?])\s+", abstract.strip())
    toks = [t for t in re.findall(r"[A-Za-z0-9]+", query) if len(t) > 2]
    for s in sents:
        low = s.lower()
        if any(t.lower() in low for t in toks):
            return s[:320]
    return sents[0][:320]


def _live_fetch(query, lit):
    """esearch -> esummary (metadata) -> efetch (abstracts) for a query."""
    ap = _api_params(lit)
    es = {"db": "pubmed", "term": query, "retmode": "json",
          "retmax": lit["top_k"], "sort": "relevance", **ap}
    if lit.get("as_of"):
        es["maxdate"] = lit["as_of"].replace("-", "/")
        es["datetype"] = "pdat"
    ids = _get_json("esearch.fcgi", es)["esearchresult"].get("idlist", [])
    if not ids:
        return []
    _throttle(lit)

    summ = _get_json("esummary.fcgi", {"db": "pubmed", "id": ",".join(ids),
                                       "retmode": "json", **ap})["result"]
    _throttle(lit)

    abstracts = {}
    try:
        xml = _get_text("efetch.fcgi", {"db": "pubmed", "id": ",".join(ids),
                                        "retmode": "xml", "rettype": "abstract", **ap})
        root = ET.fromstring(xml)
        for art in root.iter("PubmedArticle"):
            pmid_el = art.find(".//PMID")
            texts = [t.text or "" for t in art.iter("AbstractText")]
            if pmid_el is not None:
                abstracts[pmid_el.text] = " ".join(texts).strip()
    except Exception:
        pass  # abstracts are a bonus; metadata alone is still useful

    out = []
    for pmid in ids:
        meta = summ.get(pmid, {})
        doi = ""
        for aid in meta.get("articleids", []):
            if aid.get("idtype") == "doi":
                doi = aid.get("value", "")
        pubdate = meta.get("pubdate", "")
        year = pubdate.split(" ")[0][:4] if pubdate else ""
        out.append({
            "pmid": pmid,
            "doi": doi,
            "title": meta.get("title", "").rstrip("."),
            "journal": meta.get("source", ""),
            "year": year,
            "snippet": _abstract_snippet(abstracts.get(pmid, ""), query),
            "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
        })
    return out


def search(query, cfg):
    """Return literature evidence for `query`, cache-first.

    Result envelope matches the old stub ({query, matches, note}) so the loop's
    summarizer and the prediction's citation flow are unchanged.
    """
    lit = _lit_cfg(cfg)
    if not lit["enabled"] or lit["source"] == "none":
        return {"query": query, "matches": [],
                "note": "Literature search disabled for this dataset."}

    cache_dir = lit["cache_dir"]
    os.makedirs(cache_dir, exist_ok=True)
    path = os.path.join(cache_dir, _norm_key(query, lit["as_of"], lit["top_k"]) + ".json")

    if os.path.exists(path):
        with open(path) as f:
            cached = json.load(f)
        return {"query": query, "matches": cached["results"],
                "note": f"cache hit ({len(cached['results'])} refs)", "cached": True}

    if lit["source"] == "cache_only":
        return {"query": query, "matches": [],
                "note": "cache_only: no cached results for this query."}

    try:
        results = _live_fetch(query, lit)
    except Exception as exc:
        return {"query": query, "matches": [],
                "note": f"live PubMed unavailable ({type(exc).__name__}); no cache entry."}

    with open(path, "w") as f:
        json.dump({"query": query, "as_of": lit["as_of"], "fetched_via": "pubmed-eutils",
                   "results": results}, f, indent=2)
    return {"query": query, "matches": results,
            "note": f"live PubMed ({len(results)} refs, cached for reuse)", "cached": False}
