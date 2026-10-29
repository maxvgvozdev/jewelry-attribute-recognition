"""Structured UPCitemdb lookup with bounded in-process cache; no HTML scraping."""
import copy
import os
import re
import time
import threading
import requests

_CACHE = {}
_LOCK = threading.Lock()

def gtin(value):
    value = str(value or "").strip()
    if not re.fullmatch(r"\d{8}|\d{12,14}", value):
        return ""
    digits = [int(c) for c in value]
    expected = (-sum(n * (3 if i % 2 == 0 else 1)
                     for i, n in enumerate(reversed(digits[:-1])))) % 10
    return value.zfill(14) if expected == digits[-1] else ""

def parse_record(data, requested):
    target = gtin(requested)
    if not target:
        return {"found": False, "reason": "invalid_gtin"}
    matching = [x for x in data.get("items", []) if isinstance(x, dict) and
                any(gtin(x.get(k)) == target for k in ("upc", "ean", "gtin"))]
    if len(matching) != 1:
        return {"found": False, "reason": "missing_or_ambiguous_record"}
    item = matching[0]
    result = {k: item.get(k) if isinstance(item.get(k), str) else "" for k in
              ("title", "brand", "model", "description", "color", "size",
               "dimension", "weight", "category", "upc", "ean", "gtin")}
    result["images"] = list(dict.fromkeys(x for x in (item.get("images") or [])
        if isinstance(x, str) and x.startswith(("https://", "http://"))))[:10]
    result["offers"] = [dict((k, offer.get(k)) for k in
        ("merchant", "domain", "title", "link", "currency", "price", "updated_t"))
        for offer in (item.get("offers") or []) if isinstance(offer, dict) and
        isinstance(offer.get("link"), str) and offer["link"].startswith(("https://", "http://"))][:10]
    for key in ("currency", "lowest_recorded_price", "highest_recorded_price"):
        result[key] = item.get(key)
    result.update(found=True, url="https://www.upcitemdb.com/upc/" + requested)
    return result

def lookup(upc):
    if not gtin(upc):
        return {"found": False, "reason": "invalid_gtin"}
    key = os.getenv("UPCITEMDB_API_KEY", "")
    endpoint = "https://api.upcitemdb.com/prod/" + ("v1" if key else "trial") + "/lookup"
    headers = {"Accept": "application/json"}
    if key:
        headers.update(user_key=key, key_type="3scale")
    cache_key = (bool(key), gtin(upc))
    # Serialize lookups to prevent duplicate requests for the same code.
    with _LOCK:
        now = time.monotonic()
        cached = _CACHE.get(cache_key)
        if cached and cached[0] > now:
            return copy.deepcopy(cached[1])
        try:
            response = requests.get(endpoint, params={"upc": upc}, headers=headers, timeout=15)
            response.raise_for_status()
            data = response.json()
            if data.get("code") not in ("OK", "NOT_FOUND"):
                result = {"found": False, "reason": "api_error"}
            else:
                result = parse_record(data, upc)
        except (requests.RequestException, ValueError, TypeError, AttributeError):
            result = {"found": False, "reason": "lookup_unavailable"}
        ttl = 3600 if result.get("found") else 60
        if len(_CACHE) >= 256:
            _CACHE.pop(next(iter(_CACHE)))
        _CACHE[cache_key] = (now + ttl, copy.deepcopy(result))
        return result

def candidate_from_record(record, context):
    """Use only an exact barcode record with a matching brand and no known conflicts."""
    from service.product_identity import check_candidate
    def brand_key(value):
        return " ".join(re.findall(r"[a-z0-9]+", value.lower()))
    if not record.get("found") or not brand_key(record.get("brand", "")) or brand_key(record["brand"]) != brand_key(context["brand"]):
        return None
    target = gtin(context.get("upc_code"))
    if not target or not any(gtin(record.get(k)) == target for k in ("upc", "ean", "gtin")):
        return None
    text = "\n".join(record.get(k, "") for k in
                     ("title", "description", "category", "color", "size", "dimension", "weight"))
    evidence = str({k: record.get(k, "") for k in
                              ("brand", "title", "description", "model", "upc", "ean", "gtin")})
    evidence += "\nVerified equivalent UPC: " + context["upc_code"]
    item = dict(url=record["url"], product_title=record.get("title", ""),
                description=text, verification_text=evidence,
                identifiers={"upc": context["upc_code"], "mpn": record.get("model", "")},
                images=record.get("images", []))
    identity = check_candidate(context, item)
    if not identity["verified"]:
        return None
    item["identity"] = identity
    item["source"] = "UPCitemdb"
    return item
