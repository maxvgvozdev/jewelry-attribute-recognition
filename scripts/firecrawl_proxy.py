"""
Firecrawl V2 proxy script.
Searches for a product page, scrapes it with JS rendering, and extracts images from Markdown.
Usage: python firecrawl_proxy.py search "<query>"
"""
import sys
import json
import os
import re
import requests

def get_base_sku(sku: str) -> str:
    """Extracts base part of SKU before color/size suffixes (e.g., B18474D88ADI -> B18474D88)"""
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
        search_data = {}
        
        # Extract likely SKU from query to match in URLs
        words = query.split()
        sku = words[-1] if len(words) > 1 else ""
        base_sku = get_base_sku(sku)
        sku_lower = sku.lower()

        # Step 1: Search for the product page
        try:
            search_payload = {
                "query": query,
                "limit": 10,
                "sources": ["web"],
                "country": "US",
                "timeout": 30000
            }
            search_resp = requests.post(f"{base_url}/search", headers=headers, json=search_payload, timeout=60)
            search_resp.raise_for_status()
            search_data = search_resp.json()
            
            web_results = search_data.get("data", {}).get("web", [])
            
            # Filter out search/category pages, prioritize URLs containing the SKU
            for result in web_results:
                if isinstance(result, dict):
                    page_url = result.get("url", "")
                    if sku_lower and sku_lower in page_url.lower():
                        if not any(kw in page_url.lower() for kw in ['/search?', '/category/', '/collections/', 'blog', 'news']):
                            product_page_url = page_url
                            break
                            
            # Fallback to first result if no exact SKU match found in URL
            if not product_page_url and web_results:
                 product_page_url = web_results[0].get("url")

        except Exception as e:
            print(json.dumps({"error": f"Firecrawl search failed: {str(e)}"}))
            sys.exit(1)

        if not product_page_url:
            print(json.dumps({"data": []}))
            return

        # Step 2: Scrape the specific page, converting to Markdown and extracting images
        try:
            scrape_payload = {
                "url": product_page_url,
                "formats": ["markdown"], # Markdown is much better for extracting rendered images cleanly
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
            
            # Smart filtering (inspired by working logic)
            clean_images = []
            seen_urls = set()
            
            for img_url in matches:
                if len(clean_images) >= 5: # Max 5 images
                    break
                    
                if not img_url or not img_url.startswith("http"):
                    continue
                    
                if img_url in seen_urls:
                    continue
                    
                url_lower = img_url.lower()
                
                # Filter out non-product images
                if any(ext in url_lower for ext in ['.html', '.htm', '.svg', '.gif']):
                    continue
                if any(kw in url_lower for kw in ['icon', 'logo', 'avatar', 'placeholder', 'menu', 'shopping', 'bag', 'return', 'sprite', 'cookie', 'close']):
                    continue
                if any(kw in url_lower for kw in ['library', 'shared', 'background', 'gradient']):
                    continue
                    
                # If we have a SKU, strictly require it to be in the image URL to avoid generic banners
                if sku_lower and base_sku:
                    if base_sku not in url_lower and sku_lower not in url_lower:
                        continue 
                
                clean_images.append(img_url)
                seen_urls.add(img_url)

            # Construct the output that api.py expects
            output_item = {
                "url": product_page_url,
                "description": markdown[:2000], # Send markdown as text context
                "images": clean_images
            }

            print(json.dumps({"data": [output_item]}))

        except Exception as e:
            # If scrape fails, return just the search data so api.py can fallback to raw requests
            print(json.dumps({"data": [{"url": product_page_url, "description": search_data.get("data", {}).get("web", [{}])[0].get("description", ""), "images": []}]}))

if __name__ == "__main__":
    main()