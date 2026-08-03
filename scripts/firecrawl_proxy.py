"""
Firecrawl V2 proxy script.
Searches for a product page and extracts structured product data and images natively.
Usage: 
  python firecrawl_proxy.py search "<query>"
  python firecrawl_proxy.py scrape "<url>"
"""
import sys
import json
import os
import requests
from typing import Optional, List, Dict, Any

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
API_URL = "https://api.firecrawl.com/v2"

# Map of brand keywords to their official website domains
OFFICIAL_SITES = {
    'cartier': ['www.cartier.com', 'media.cartier.com'],
    'tiffany': ['www.tiffany.com', 'www.tiffany.ca'],
    'vancleef': ['www.vancleefarpels.com'],
    'yurman': ['www.davidyurman.com'],
    'brilliant earth': ['www.brilliantearth.com'],
}

# Pre-compiled set for O(1) lookup to speed up URL filtering
SKIP_URL_KEYWORDS = {'/search?', '/category/', '/collections/', '/blog', '/news'}

# LLM Prompt for text extraction
TEXT_EXTRACTION_PROMPT = """IGNORE the website header, footer, and all navigation menus. 
Focus ONLY on the main product details section for this specific jewelry item.
Extract the product title, full description text, materials/metals used, and gemstones used."""

def _do_scrape(url_to_scrape: str, headers: dict) -> dict:
    """Core scraping logic used by both search and direct scrape commands."""
    try:
        scrape_payload = {
            "url": url_to_scrape,
            "formats": [
                {
                    "type": "json",
                    "prompt": TEXT_EXTRACTION_PROMPT,
                    "schema": {
                        "type": "object",
                        "properties": {
                            "product_title": {"type": ["string", "null"]},
                            "description": {"type": ["string", "null"]},
                            "materials_text": {"type": ["string", "null"]}
                        }
                    }
                },
                {"type": "product"} # Extract clean gallery images deterministically
            ],
            "onlyMainContent": False,
            "waitFor": 5000,
            "blockAds": True,
            "location": {"country": "US", "languages": ["en-US"]}
        }
        
        scrape_resp = requests.post(f"{API_URL}/scrape", headers=headers, json=scrape_payload, timeout=120)
        scrape_resp.raise_for_status()
        scrape_data = scrape_resp.json()
        
        # 1. Extract text
        extracted_data = scrape_data.get("data", {}).get("json", {})
        text_parts = [
            p for p in [
                extracted_data.get("product_title", ""), 
                extracted_data.get("description", ""), 
                extracted_data.get("materials_text", "")
            ] if p
        ]
        text_context = "\n".join(text_parts)
        
        # 2. Extract images from 'product' variants array
        clean_images = []
        product_data = scrape_data.get("data", {}).get("product", {})
        if product_data and product_data.get("variants"):
            for variant in product_data["variants"]:
                for img in variant.get("images", []):
                    img_url = img.get("url", "") if isinstance(img, dict) else img
                    if img_url.startswith("http"):
                        clean_images.append(img_url)

        # 3. Fallback to OG image
        if not clean_images:
            og_image = scrape_data.get("data", {}).get("metadata", {}).get("og:image", "")
            if og_image and og_image.startswith("http"):
                clean_images.append(og_image)

        return {"url": url_to_scrape, "description": text_context, "images": clean_images}

    except Exception as e:
        import traceback
        # Print the full error to stderr so api.py logs it, then exit with code 1
        traceback.print_exc(file=sys.stderr)
        sys.exit(1)


def main() -> None:
    if len(sys.argv) < 3:
        print(json.dumps({"error": "Usage: python firecrawl_proxy.py [search|scrape] <query_or_url>"}))
        sys.exit(1)

    command = sys.argv[1]
    param = sys.argv[2]
    api_key = os.getenv("FIRECRAWL_API_KEY")

    if not api_key:
        print(json.dumps({"error": "Set FIRECRAWL_API_KEY env var"}))
        sys.exit(1)

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    # -----------------------------------------------------------------
    # COMMAND: SEARCH
    # -----------------------------------------------------------------
    if command == "search":
        product_page_url = None
        words = param.split()
        brand_guess = words[0].lower() if words else ""
        sku = words[-1] if len(words) > 1 else ""
        sku_lower = sku.lower()

        official_domains = []
        for key, domains in OFFICIAL_SITES.items():
            key_parts = key.split()
            if any(part in brand_guess for part in key_parts):
                official_domains = domains
                break

        try:
            search_payloads = []
            if official_domains:
                search_payloads.append({
                    "query": param,
                    "limit": 10,
                    "country": "US",
                    "includeDomains": official_domains
                })
            search_payloads.append({"query": param, "limit": 10, "country": "US"})

            for search_payload in search_payloads:
                search_resp = requests.post(f"{API_URL}/search", headers=headers, json=search_payload, timeout=60)
                search_resp.raise_for_status()
                search_data = search_resp.json()
                
                web_results = search_data.get("data", {}).get("web", [])
                valid_results = [
                    r for r in web_results 
                    if isinstance(r, dict) and not (SKIP_URL_KEYWORDS & set(r.get("url", "").lower().split('/')))
                ]
                
                def get_url(result: Dict[str, Any]) -> str:
                    return result.get("url", "").lower()

                if official_domains and not product_page_url:
                    for result in valid_results:
                        page_url = get_url(result)
                        if sku_lower in page_url and any(domain in page_url for domain in official_domains):
                            product_page_url = result.get("url")
                            break
                            
                if not product_page_url:
                    for result in valid_results:
                        if sku_lower in get_url(result):
                            product_page_url = result.get("url")
                            break

                if not product_page_url and valid_results:
                    product_page_url = valid_results[0].get("url")

                if product_page_url:
                    break

        except Exception as e:
            import traceback
            traceback.print_exc(file=sys.stderr)
            sys.exit(1)

        if not product_page_url:
            print(json.dumps({"data": []}))
            return

        # If search found a URL, scrape it immediately
        output_item = _do_scrape(product_page_url, headers)
        print(json.dumps({"data": [output_item]}))

    # -----------------------------------------------------------------
    # COMMAND: DIRECT SCRAPE
    # -----------------------------------------------------------------
    elif command == "scrape":
        output_item = _do_scrape(param, headers)
        print(json.dumps({"data": [output_item]}))

    else:
        print(json.dumps({"error": f"Unknown command: {command}"}))
        sys.exit(1)

if __name__ == "__main__":
    main()