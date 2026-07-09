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

        # Step 2: Scrape using Firecrawl's Native Product extraction (NO MORE REGEX!)
        try:
            scrape_payload = {
                "url": product_page_url,
                "formats": ["product", "markdown"], 
                "onlyMainContent": False, # Set to False to catch lazy-loaded gallery images!
                "waitFor": 5000,            # Give Cartier's JS gallery 5 seconds to render
                "blockAds": True
            }
            
            scrape_resp = requests.post(f"{base_url}/scrape", headers=headers, json=scrape_payload, timeout=120)
            scrape_resp.raise_for_status()
            scrape_data = scrape_resp.json()
            
            product_data = scrape_data.get("data", {}).get("product", {})
            markdown = scrape_data.get("data", {}).get("markdown", "")
            
            # Extract images natively from the structured product object
            clean_images = []
            seen_urls = set()
            unverified_images = [] # Hold URLs here first to check if they are real images
            
            # Look inside variants (standard for e-commerce like Cartier/DY)
            for variant in product_data.get("variants", []):
                for img in variant.get("images", []):
                    img_url = img.get("url", "")
                    if img_url and img_url.startswith("http") and img_url not in seen_urls:
                        unverified_images.append(img_url)
                        seen_urls.add(img_url)
                        
            # Fallback: Look at root product level
            for img in product_data.get("images", []):
                img_url = img.get("url", "")
                if img_url and img_url.startswith("http") and img_url not in seen_urls:
                    unverified_images.append(img_url)
                    seen_urls.add(img_url)

            # VALIDATION: Only accept URLs that actually look like images, otherwise discard them and fallback to Markdown
            for img_url in unverified_images:
                url_lower = img_url.lower()
                is_image = (
                    any(ext in url_lower for ext in ['.jpg', '.jpeg', '.png', '.webp']) or
                    any(cdn in url_lower for cdn in ['/images/', '/large/', 'transform.', 'demandware.static', 'carprodcard', '/dam/'])
                )
                if is_image:
                    clean_images.append(img_url)

            # FINAL FALLBACK: If product format found 0 real images, parse the Markdown text
            if not clean_images and markdown:
                import re
                img_pattern = r'!\[.*?\]\((https?://[^\s\)]+)\)'
                matches = re.findall(img_pattern, markdown)
                for img_url in matches:
                    if len(clean_images) >= 5:
                        break
                    if img_url and img_url.startswith("http") and img_url not in seen_urls:
                        url_lower = img_url.lower()
                        if any(kw in url_lower for kw in ['icon', 'logo', 'placeholder', 'menu', 'clickToLoad']):
                            continue
                        clean_images.append(img_url)
                        seen_urls.add(img_url)

            # FALLBACK: If product format found 0 images (e.g., Cartier non-English pages), parse markdown
            if not clean_images and markdown:
                import re
                img_pattern = r'!\[.*?\]\((https?://[^\s\)]+)\)'
                matches = re.findall(img_pattern, markdown)
                for img_url in matches:
                    if len(clean_images) >= 5:
                        break
                    if img_url and img_url.startswith("http") and img_url not in seen_urls:
                        url_lower = img_url.lower()
                        if any(kw in url_lower for kw in ['icon', 'logo', 'placeholder', 'menu', 'clickToLoad']):
                            continue
                        clean_images.append(img_url)
                        seen_urls.add(img_url)

            # Build rich text context: Product Title + Description + Markdown
            title = product_data.get("title", "")
            description = product_data.get("description", "")
            context_parts = []
            if title: context_parts.append(title)
            if description: context_parts.append(description)
            if markdown: context_parts.append(markdown[:4000])
            
            text_context = "\n\n".join(context_parts)

            output_item = {
                "url": product_page_url,
                "description": text_context,
                "images": clean_images[:5] # Max 5 images for the AI
            }

            print(json.dumps({"data": [output_item]}))

        except Exception as e:
            print(json.dumps({"data": [{"url": product_page_url, "description": "", "images": []}]}))

if __name__ == "__main__":
    main()