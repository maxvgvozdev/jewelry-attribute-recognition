"""
Firecrawl V2 proxy script.
Searches for a product page, prioritizing official brand sites,
scrapes it with JS rendering, and extracts images from Markdown.
Usage: python firecrawl_proxy.py search "<query>"
"""
import sys
import json
import os
import re
import requests

# Map of brand keywords to their official website domains (from working logic)
OFFICIAL_SITES = {
    'cartier': ['www.cartier.com'],
    'tiffany': ['www.tiffany.com', 'www.tiffany.ca'],
    'vancleef': ['www.vancleefarpels.com'],
    'van cleef': ['www.vancleefarpels.com'],
    'yurman': ['www.davidyurman.com', 'media.davidyurman.com'],
    'david yurman': ['www.davidyurman.com', 'media.davidyurman.com'],
    'brilliant earth': ['www.brilliantearth.com'],
}

def get_base_sku(sku: str) -> str:
    """Extracts base part of SKU before color/size suffixes"""
    if not sku:
        return ""
    base = re.split(r'[-_]?(ADI|AAM|DI|AM|PLAT|WG|YG|RG|\d+K|\d+KT|\d+KY)$', sku, flags=re.IGNORECASE)[0]
    return base.strip()

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
        base_sku = get_base_sku(sku)
        sku_lower = sku.lower()

        # Find official domains for this brand
        official_domains = []
        for key, domains in OFFICIAL_SITES.items():
            if key in brand_guess or brand_guess in key:
                official_domains = domains
                break

        # Step 1: Search via Firecrawl V2
        try:
            search_payload = {
                "query": query,
                "limit": 15,
                "sources": ["web"],
                "country": "US",
                "timeout": 30000
            }
            search_resp = requests.post(f"{base_url}/search", headers=headers, json=search_payload, timeout=60)
            search_resp.raise_for_status()
            search_data = search_resp.json()
            
            web_results = search_data.get("data", {}).get("web", [])
            
            # Filter out search/category/blog pages
            valid_results = []
            for result in web_results:
                if isinstance(result, dict):
                    page_url = result.get("url", "")
                    if not any(kw in page_url.lower() for kw in ['/search?', '/category/', '/collections/', '/blog', '/news']):
                        valid_results.append(result)
            
            # Priority 1: Official site with exact SKU in URL
            if official_domains:
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

        except Exception as e:
            print(json.dumps({"error": f"Firecrawl search failed: {str(e)}"}))
            sys.exit(1)

        if not product_page_url:
            print(json.dumps({"data": []}))
            return

        # Step 2: Scrape the page for images using Firecrawl V2 Markdown
        try:
            scrape_payload = {
                "url": product_page_url,
                "formats": ["markdown"],
                "onlyMainContent": True,
                "waitFor": 3000,
                "blockAds": True
            }
            
            scrape_resp = requests.post(f"{base_url}/scrape", headers=headers, json=scrape_payload, timeout=120)
            scrape_resp.raise_for_status()
            scrape_data = scrape_resp.json()
            
            markdown = scrape_data.get("data", {}).get("markdown", "")
            
            # Extract images from Markdown format: ![alt](url)
            img_pattern = r'!\[.*?\]\((https?://[^\s\)]+)\)'
            matches = re.findall(img_pattern, markdown)
            
            # Smart filtering (skip logos/icons, strictly require SKU in URL)
            clean_images = []
            seen_urls = set()
            
            for img_url in matches:
                if len(clean_images) >= 5:
                    break
                if not img_url or not img_url.startswith("http"):
                    continue
                if img_url in seen_urls:
                    continue
                    
                url_lower = img_url.lower()
                
                # Filter out non-image files and UI elements
                if any(ext in url_lower for ext in ['.html', '.htm', '.svg', '.gif', '.png']):
                    continue
                if any(kw in url_lower for kw in ['icon', 'logo', 'avatar', 'placeholder', 'menu', 'shopping', 'bag', 'return', 'sprite', 'cookie', 'close', 'background']):
                    continue
                if any(kw in url_lower for kw in ['library', 'shared', 'gradient']):
                    continue
                    
                # Strictly require SKU in image URL to prevent generic banners
                if sku_lower and base_sku:
                    if base_sku not in url_lower and sku_lower not in url_lower:
                        continue 
                
                clean_images.append(img_url)
                seen_urls.add(img_url)

            output_item = {
                "url": product_page_url,
                "description": markdown[:2000],
                "images": clean_images
            }

            print(json.dumps({"data": [output_item]}))

        except Exception as e:
            print(json.dumps({"data": [{"url": product_page_url, "description": "", "images": []}]}))

if __name__ == "__main__":
    main()