"""Firecrawl product discovery. Structured context is passed on stdin by the API.
Standalone usage remains: python firecrawl_proxy.py search "Brand identifier".
"""
import json
import os
import sys
import time
from pathlib import Path
from urllib.parse import urlparse
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from service.product_identity import check_candidate, build_queries

API_URL = "https://api.firecrawl.dev/v2"

def scrape(url, headers, timeout=60):
    payload = {
        "url": url,
        "formats": ["markdown", {"type": "json",
            "prompt": "Extract ONLY the current product's title, brand, manufacturer reference/MPN, SKU, UPC/GTIN, description, materials and gemstones. Exclude navigation, recommendations and brand-wide ethical sourcing claims. Copy identifiers exactly; use null when absent.",
            "schema": {"type": "object", "properties": {
                k: {"type": ["string", "null"]} for k in
                ("product_title", "brand", "mpn", "sku", "upc", "description", "materials_text")
            }}}, {"type": "product"}],
        "onlyMainContent": True, "waitFor": 3000, "blockAds": True,
        "location": {"country": "US", "languages": ["en-US"]}
    }
    response = requests.post(API_URL + "/scrape", headers=headers, json=payload, timeout=timeout)
    response.raise_for_status()
    data = response.json().get("data") or {}
    extracted = data.get("json") or {}
    # Only raw page text is allowed to confirm identity. Generated extraction alone
    # must not turn an unverified candidate into an accepted product.
    raw = data.get("markdown") or ""
    description = "\n".join(str(extracted.get(k) or "") for k in
                            ("product_title", "description", "materials_text"))
    images = []
    product = data.get("product") or {}
    # Reject ambiguous multi-variant galleries rather than mix different products.
    variants = product.get("variants") or []
    if len(variants) == 1:
        for image in variants[0].get("images") or []:
            value = image.get("url", "") if isinstance(image, dict) else image
            if isinstance(value, str) and value.startswith(("http://", "https://")) and value not in images:
                images.append(value)
    if not images:
        og = (data.get("metadata") or {}).get("og:image")
        if isinstance(og, str) and og.startswith(("http://", "https://")):
            images.append(og)
    return {"url": url, "description": description, "product_title": extracted.get("product_title") or "",
            "verification_text": raw, "identifiers": {k: extracted.get(k) for k in ("mpn", "sku", "upc")}, "images": images}

def main():
    if len(sys.argv) < 3:
        raise ValueError("Usage: firecrawl_proxy.py search|scrape <query|url>")
    command, param = sys.argv[1:3]
    context = json.loads(sys.stdin.read()) if len(sys.argv) > 3 and sys.argv[3] == "--context" else None
    key = os.environ.get("FIRECRAWL_API_KEY")
    if not key:
        raise ValueError("Set FIRECRAWL_API_KEY env var")
    headers = {"Authorization": "Bearer " + key, "Content-Type": "application/json"}
    if context is None:
        # Compatibility for interactive CLI, but callers should provide structured context.
        brand, _, identifier = param.rpartition(" ")
        context = {"brand": brand, "vendor_item_number": identifier}
    deadline = time.monotonic() + 420
    urls, seen, rejected, errors = [], set(), [], []
    record = context.get("upc_record") or {}
    if command == "scrape":
        urls = [param]
    elif command == "search":
        # Gather multiple search queries before selecting a page; never accept result #1 blindly.
        for offer in record.get("offers", [])[:3]:
            link = offer.get("link", "")
            if link.startswith(("https://", "http://")) and link not in seen:
                urls.append(link)
                seen.add(link)
        for query in build_queries(context)[:4]:
            if time.monotonic() > deadline - 60:
                break
            try:
                response = requests.post(API_URL + "/search", headers=headers,
                    json={"query": query, "limit": 5, "country": "US"}, timeout=30)
                response.raise_for_status()
                for result in (response.json().get("data") or {}).get("web") or []:
                    url = result.get("url", "")
                    path = urlparse(url).path.lower()
                    if not url.startswith(("https://", "http://")) or any(
                        part in path for part in ("/collections", "/search", "/blog", "/news", "/category")):
                        continue
                    if url not in seen:
                        urls.append(url)
                        seen.add(url)
            except requests.RequestException as exc:
                errors.append(str(exc))
    else:
        raise ValueError("Unknown command")
    for url in urls[:5]:
        remaining = deadline - time.monotonic()
        if remaining < 5:
            break
        try:
            item = scrape(url, headers, timeout=min(60, remaining))
            identity = check_candidate(context, item)
            if identity["verified"]:
                item.pop("verification_text", None)
                item["identity"] = identity
                print(json.dumps({"data": [item], "rejected": rejected, "errors": errors}))
                return
            rejected.append({"url": url, **identity})
        except (requests.RequestException, ValueError, TypeError) as exc:
            errors.append(str(exc))
    if errors and not rejected:
        raise RuntimeError("Product discovery failed: " + errors[-1])
    print(json.dumps({"data": [], "rejected": rejected, "errors": errors}))

if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
