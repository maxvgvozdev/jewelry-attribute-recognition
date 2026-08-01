"""
Firecrawl V2 proxy script.
Searches for a product page and extracts structured product data and images natively.
Usage: python firecrawl_proxy.py search "<query>"
"""
import sys
import json
import os
import re
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
# Note: 'van cleef' is implicitly handled by checking if 'van' or 'cleef' is in the brand_guess.

# Pre-compiled set for O(1) lookup to speed up URL filtering
SKIP_URL_KEYWORDS = {'/search?', '/category/', '/collections/', '/blog', '/news'}

# LLM Prompt for text extraction
TEXT_EXTRACTION_PROMPT = """IGNORE the website header, footer, and all navigation menus. 
Focus ONLY on the main product details section for this specific jewelry item.
Extract the product title, full description text, materials/metals used, and gemstones used."""

def main() -> None:
    if len(sys.argv) < 3:
        print(json.dumps({"error": "Usage: python firecrawl_proxy.py search <query>"}))
        sys.exit(1)

    command = sys.argv[1]
    query = sys.argv[2]
    api_key = os.getenv("FIRECRAWL_API_KEY")

    if not api_key:
        print(json.dumps({"error": "Set FIRECRAWL_API_KEY env var"}))
        sys.exit(1)

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    if command == "search":
        product_page_url = None
        
        # Extract brand and SKU from query
        words = query.split()
        brand_guess = words[0].lower() if words else ""
        sku = words[-1] if len(words) > 1 else ""
        sku_lower = sku.lower()

        # Find official domains for this brand
        official_domains = []
        for key, domains in OFFICIAL_SITES.items():
            # Handle "van cleef" by checking both words against the brand guess
            key_parts = key.split()
            if any(part in brand_guess for part in key_parts):
                official_domains = domains
                break

        # Step 1: Search via Firecrawl V2
        try:
            search_queries = [query]
            if official_domains:
                search_queries.insert(0, f"site:{official_domains[0]} {query}")

            for search_query in search_queries:
                search_payload = {
                    "query": search_query,
                    "limit": 10,
                    "searchType": "Web",
                    "country": "US",
                    "timeout": 30000
                }
                
                search_resp = requests.post(f"{API_URL}/search", headers=headers, json=search_payload, timeout=60)
                search_resp.raise_for_status()
                search_data = search_resp.json()
                
                web_results = search_data.get("data", {}).get("web", [])
                
                # Filter out search/category/blog pages using pre-compiled set for O(1) lookup
                valid_results = [
                    r for r in web_results 
                    if isinstance(r, dict) and not (SKIP_URL_KEYWORDS & set(r.get("url", "").lower().split('/')))
                ]
                
                # Extract URL helper to avoid repeating .get() and .lower() multiple times
                def get_url(result: Dict[str, Any]) -> str:
                    return result.get("url", "").lower()

                # Priority 1: Official site with exact SKU in URL
                if official_domains and not product_page_url:
                    for result in valid_results:
                        page_url = get_url(result)
                        if sku_lower in page_url:
                            if any(domain in page_url for domain in official_domains):
                                product_page_url = result.get("url")
                                break
                                
                # Priority 2: Any site with exact SKU in URL
                if not product_page_url:
                    for result in valid_results:
                        if sku_lower in get_url(result):
                            product_page_url = result.get("url")
                            break

                # Priority 3: First valid result
                if not product_page_url and valid_results:
                    product_page_url = valid_results[0].get("url")

                if product_page_url:
                    break

        except requests.exceptions.Timeout:
            print(json.dumps({"error": "Firecrawl search timed out."}))
            sys.exit(1)
        except requests.exceptions.HTTPError as e:
            print(json.dumps({"error": f"Firecrawl HTTP error during search: {e.response.status_code} - {e.response.text[:200]}"}))
            sys.exit(1)
        except Exception as e:
            print(json.dumps({"error": f"Unexpected error during search: {str(e)}"}))
            sys.exit(1)

        if not product_page_url:
            print(json.dumps({"data": []}))
            return

        # Step 2: Scrape using JSON for text + OG Image for the primary product shot
        try:
            scrape_payload = {
                "url": product_page_url,
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
                    }
                ],
                "onlyMainContent": False,
                "waitFor": 5000,
                "blockAds": True
            }
            
            scrape_resp = requests.post(f"{API_URL}/scrape", headers=headers, json=scrape_payload, timeout=120)
            scrape_resp.raise_for_status()
            scrape_data = scrape_resp.json()
            
            # 1. Extract perfect text from JSON format
            extracted_data = scrape_data.get("data", {}).get("json", {})
            title = extracted_data.get("product_title", "")
            desc = extracted_data.get("description", "")
            materials = extracted_data.get("materials_text", "")
            text_parts = [p for p in [title, desc, materials] if p]
            text_context = "\n".join(text_parts)
            
            # 2. Extract the primary product image safely from metadata
            clean_images = []
            og_image = scrape_data.get("data", {}).get("metadata", {}).get("og:image", "")
            
            if og_image and og_image.startswith("http"):
                # Use the OG image EXACTLY as provided to avoid triggering 
                # strict CDN hotlink protection on raw master files.
                clean_images.append(og_image)

            output_item = {
                "url": product_page_url,
                "description": text_context,
                "images": clean_images
            }

            print(json.dumps({"data": [output_item]}))

        except requests.exceptions.Timeout:
            print(json.dumps({"data": [{"url": product_page_url, "description": "", "images": []}]}))
        except requests.exceptions.HTTPError as e:
            print(json.dumps({"data": [{"url": product_page_url, "description": "", "images": []}]}))
        except Exception as e:
            print(json.dumps({"data": [{"url": product_page_url, "description": "", "images": []}]}))

if __name__ == "__main__":
    main()