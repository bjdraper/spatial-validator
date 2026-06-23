"""Cache-first UniProt protein annotation lookup (UniProt REST API).

The Critic uses this to decide whether a DEG is a specialised cell-type biomarker
or a housekeeping / ubiquitous protein: function description, subcellular
localization, and keywords (e.g. a transcription factor restricted to one lineage
vs. a cytoskeletal/ribosomal housekeeping protein).

Mirrors agent/literature.py exactly:
  * stdlib only (urllib) — no dependency on any SDK, runs anywhere
  * persistent on-disk JSON cache keyed by (gene, taxon); commit the cache dir to
    freeze an offline/reproducible snapshot
  * `source: cache_only` (or no network) -> cache hits only, misses degrade
    gracefully to "not found" instead of erroring

Species -> taxon id is taken from cfg['species'] (human=9606, mouse=10090), or an
explicit cfg['uniprot']['taxon_id'] override.
"""
import hashlib
import json
import os
import urllib.parse
import urllib.request

_REST = "https://rest.uniprot.org/uniprotkb/search"
_FIELDS = "accession,protein_name,cc_function,cc_subcellular_location,keyword,gene_primary"
_TAXON = {"human": "9606", "mouse": "10090", "rat": "10116"}


def _uni_cfg(cfg):
    uni = dict(cfg.get("uniprot") or {})
    uni.setdefault("enabled", False)
    uni.setdefault("source", "uniprot")       # uniprot | cache_only | none
    uni.setdefault("cache_dir", "data/uniprotcache")
    taxon = uni.get("taxon_id") or _TAXON.get(str(cfg.get("species", "")).lower(), "")
    uni["taxon_id"] = str(taxon)
    return uni


def _cache_key(gene, taxon):
    basis = f"{gene.strip().lower()}|tax={taxon}"
    return hashlib.sha1(basis.encode()).hexdigest()[:16]


def _get_json(url):
    with urllib.request.urlopen(url, timeout=12) as r:
        return json.load(r)


def _parse_entry(entry):
    """Pull the human-readable bits out of one UniProtKB JSON result."""
    desc = entry.get("proteinDescription", {})
    rec = desc.get("recommendedName") or {}
    protein_name = (rec.get("fullName") or {}).get("value", "")

    function, localization, keywords = "", [], []
    for c in entry.get("comments", []):
        ctype = c.get("commentType")
        if ctype == "FUNCTION":
            for t in c.get("texts", []):
                if t.get("value"):
                    function = t["value"]
                    break
        elif ctype == "SUBCELLULAR LOCATION":
            for loc in c.get("subcellularLocations", []):
                v = (loc.get("location") or {}).get("value")
                if v:
                    localization.append(v)
    for kw in entry.get("keywords", []):
        if kw.get("name"):
            keywords.append(kw["name"])

    return protein_name, function, localization, keywords


def _live_fetch(gene, taxon):
    """One UniProtKB search, best (reviewed-preferred) hit for gene+organism."""
    q = f"gene:{gene} AND organism_id:{taxon}" if taxon else f"gene:{gene}"
    params = {"query": q, "fields": _FIELDS, "format": "json", "size": "5"}
    url = f"{_REST}?" + urllib.parse.urlencode(params)
    data = _get_json(url)
    results = data.get("results", [])
    if not results:
        return None
    # Prefer a reviewed (Swiss-Prot) entry over unreviewed (TrEMBL).
    results.sort(key=lambda e: 0 if e.get("entryType", "").startswith("UniProtKB reviewed") else 1)
    entry = results[0]
    protein_name, function, localization, keywords = _parse_entry(entry)
    return {
        "accession": entry.get("primaryAccession", ""),
        "protein_name": protein_name,
        "function": function[:600],
        "subcellular_location": localization,
        "keywords": keywords,
        "reviewed": entry.get("entryType", "").startswith("UniProtKB reviewed"),
        "url": f"https://www.uniprot.org/uniprotkb/{entry.get('primaryAccession', '')}/entry",
    }


def lookup(gene, cfg):
    """Return UniProt annotation for `gene`, cache-first. Never raises."""
    uni = _uni_cfg(cfg)
    g = (gene or "").strip()
    if not uni["enabled"] or uni["source"] == "none":
        return {"gene": gene, "found": False,
                "note": "UniProt lookup disabled for this dataset."}
    if not g:
        return {"gene": gene, "found": False, "note": "Empty gene symbol."}

    cache_dir = uni["cache_dir"]
    os.makedirs(cache_dir, exist_ok=True)
    path = os.path.join(cache_dir, _cache_key(g, uni["taxon_id"]) + ".json")

    if os.path.exists(path):
        with open(path) as f:
            cached = json.load(f)
        out = dict(cached["result"]) if cached.get("result") else {"found": False}
        out.update({"gene": gene, "cached": True})
        out.setdefault("found", bool(cached.get("result")))
        return out

    if uni["source"] == "cache_only":
        return {"gene": gene, "found": False,
                "note": "cache_only: no cached UniProt entry for this gene."}

    try:
        result = _live_fetch(g, uni["taxon_id"])
    except Exception as exc:
        return {"gene": gene, "found": False,
                "note": f"live UniProt unavailable ({type(exc).__name__}); no cache entry."}

    with open(path, "w") as f:
        json.dump({"gene": g, "taxon_id": uni["taxon_id"], "result": result}, f, indent=2)

    if not result:
        return {"gene": gene, "found": False,
                "note": "No UniProt entry for this gene/organism."}
    out = dict(result)
    out.update({"gene": gene, "found": True, "cached": False})
    return out
