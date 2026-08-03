"""
Firecrawl V2 proxy script.
Searches for a product page and extracts structured product data and images natively.
Usage: python firecrawl_proxy.py search "<query>"
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
        product_page_result = None
        
        # Extract brand and SKU from query
        words = query.split()
        brand_guess = words[0].lower() if words else ""
        sku = words[-1] if len(words) > 1 else ""
        sku_lower = sku.lower()

        # Find official domains for this brand
        official_domains = []
        for key, domains in OFFICIAL_SITES.items():
            key_parts = key.split()
            if any(part in brand_guess for part in key_parts):
                official_domains = domains
                break

        # Step 1: Search via Firecrawl V2 (with integrated Scrape Options)
        try:
            search_queries = [query]
            if official_domains:
                search_queries.insert(0, f"site:{official_domains[0]} {query}")

            for search_query in search_queries:
                # MAGIC: We pass scrapeOptions directly into the search payload.
                # This does the search AND the scrape in one single atomic API call!
                search_payload = {
                    "query": search_query,
                    "limit": 5,
                    "country": "US", # Force US-based search results
                    "scrapeOptions": {
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
                            {
                                "type": "images" # Natively extracts all DOM images, no regex needed
                            }
                        ],
                        # MAGIC: Forces the headless browser to emulate a US user.
                        # This makes Cartier/boutiques serve the English page natively.
                        "location": {
                            "country": "US",
                            "languages": ["en-US"]
                        },
                        "waitFor": 5000,
                        "blockAds": True
                    }
                }
                
                search_resp = requests.post(f"{API_URL}/search", headers=headers, json=search_payload, timeout=120)
                search_resp.raise_for_status()
                search_data = search_resp.json()
                
                web_results = search_data.get("data", {}).get("web", [])
                
                # Filter out search/category/blog pages
                valid_results = [
                    r for r in web_results 
                    if isinstance(r, dict) and not (SKIP_URL_KEYWORDS & set(r.get("url", "").lower().split('/')))
                ]

                def get_url(result: Dict[str, Any]) -> str:
                    return result.get("url", "").lower()

                # Priority 1: Official site with exact SKU in URL
                if official_domains and not product_page_result:
                    for result in valid_results:
                        page_url = get_url(result)
                        if sku_lower in page_url:
                            if any(domain in page_url for domain in official_domains):
                                product_page_result = result
                                break
                                
                # Priority 2: Any site with exact SKU in URL
                if not product_page_result:
                    for result in valid_results:
                        if sku_lower in get_url(result):
                            product_page_result = result
                            break

                # Priority 3: First valid result
                if not product_page_result and valid_results:
                    product_page_result = valid_results[0]

                if product_page_result:
                    break

        except requests.exceptions.Timeout:
            print(json.dumps({"error": "Firecrawl search timed out."}))
            sys.exit(1)
        except requests.exceptions.HTTPError as e:
            print(json.dumps({"error": f"Firecrawl HTTP error: {e.response.status_code} - {e.response.text[:200]}"}))
            sys.exit(1)
        except Exception as e:
            print(json.dumps({"error": f"Unexpected error during search: {str(e)}"}))
            sys.exit(1)

        if not product_page_result:
            print(json.dumps({"data": []}))
            return

        # -----------------------------------------------------------------
        # STEP 2 IS COMPLETELY REMOVED!
        # Because we used scrapeOptions in Step 1, the search result 
        # ALREADY contains the extracted JSON text and the Images array.
        # We just parse it directly.
        # -----------------------------------------------------------------
        
        try:
            # 1. Extract perfect text from the natively extracted JSON format
            extracted_data = product_page_result.get("json", {})
            title = extracted_data.get("product_title", "")
            desc = extracted_data.get("description", "")
            materials = extracted_data.get("materials_text", "")
            text_parts = [p for p in [title, desc, materials] if p]
            text_context = "\n".join(text_parts)
            
            # 2. Extract images natively (no regex, no OG tags)
            clean_images = []
            raw_images = product_page_result.get("images", [])
            
            if isinstance(raw_images, list):
                for img in raw_images:
                    # Firecrawl images format usually returns strings, but handle objects just in case
                    img_url = img if isinstance(img, str) else img.get("url", "")
                    
                    if not img_url.startswith("http"):
                        continue
                    
                    # Basic safety filter to skip data URIs or obvious tiny icons/logos 
                    # if Firecrawl's native extractor accidentally grabs one
                    if any(skip in img_url.lower() for skip in ['data:image', 'favicon', 'sprite.svg']):
                        continue
                        
                    clean_images.append(img_url)

            output_item = {
                "url": product_page_result.get("url"),
                "description": text_context,
                "images": clean_images
            }

            print(json.dumps({"data": [output_item]}))

        except Exception as e:
            # Fallback to empty data if parsing the combined result fails
            print(json.dumps({"data": [{"url": product_page_result.get("url"), "description": "", "images": []}]}))

if __name__ == "__main__":
    main()