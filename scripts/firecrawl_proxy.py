"""
Firecrawl V2 proxy script.
Searches for a product page and extracts structured product data and images natively.
Usage: python firecrawl_proxy.py search "<query>"
"""
import sys
import json
import os
import requests

# Map of brand keywords to their official website domains
OFFICIAL_SITES = {
    'cartier': ['www.cartier.com', 'media.cartier.com'],
    'tiffany': ['www.tiffany.com', 'www.tiffany.ca'],
    'vancleef': ['www.vancleefarpels.com'],
    'van cleef': ['www.vancleefarpels.com'],
    'yurman': ['www.davidyurman.com'],
    'david yurman': ['www.davidyurman.com'],
    'brilliant earth': ['www.brilliantearth.com'],
}

def main():
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
    base_url = "https://api.firecrawl.dev/v2"

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
            if key in brand_guess or brand_guess in key:
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
                    "sources": ["web"],
                    "country": "US",
                    "timeout": 30000
                }
                
                search_resp = requests.post(f"{base_url}/search", headers=headers, json=search_payload, timeout=60)
                search_resp.raise_for_status()
                search_data = search_resp.json()
                
                web_results = search_data.get("data", {}).get("web", [])
                
                # Filter out search/category/blog pages
                valid_results = [
                    r for r in web_results 
                    if isinstance(r, dict) and not any(kw in r.get("url", "").lower() for kw in ['/search?', '/category/', '/collections/', '/blog', '/news'])
                ]
                
                # Priority 1: Official site with exact SKU in URL
                if official_domains and not product_page_url:
                    for result in valid_results:
                        page_url = result.get("url", "")
                        if sku_lower and sku_lower in page_url.lower():
                            if any(domain in page_url for domain in official_domains):
                                product_page_url = page_url
                                break
                                
                # Priority 2: Any site with exact SKU in URL
                if not product_page_url:
                    for result in valid_results:
                        page_url = result.get("url", "")
                        if sku_lower and sku_lower in page_url.lower():
                            product_page_url = page_url
                            break

                # Priority 3: First valid result
                if not product_page_url and valid_results:
                    product_page_url = valid_results[0].get("url")

                if product_page_url:
                    break

        except Exception as e:
            print(json.dumps({"error": f"Firecrawl search failed: {str(e)}"}))
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
                        "prompt": """IGNORE the website header, footer, and all navigation menus. 
                        Focus ONLY on the main product details section for this specific jewelry item.
                        Extract the product title, full description text, materials/metals used, 
                        and gemstones used.""",
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
            
            scrape_resp = requests.post(f"{base_url}/scrape", headers=headers, json=scrape_payload, timeout=120)
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
                # Strip any thumbnail transformations and URL parameters to get the raw master file
                clean_url = og_image.split('.transform.')[0].split('?')[0]
                if any(ext in clean_url.lower() for ext in ['.jpg', '.jpeg', '.png', '.webp']):
                    clean_images.append(clean_url)

            output_item = {
                "url": product_page_url,
                "description": text_context,
                "images": clean_images
            }

            print(json.dumps({"data": [output_item]}))

        except Exception as e:
            print(json.dumps({"data": [{"url": product_page_url, "description": "", "images": []}]}))

if __name__ == "__main__":
    main()