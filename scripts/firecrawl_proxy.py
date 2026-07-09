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

        # Step 2: Scrape using targeted JSON extraction + Raw HTML for images
        try:
            scrape_payload = {
                "url": product_page_url,
                "formats": [
                    {
                        "type": "json",
                        "prompt": """IGNORE the website header, footer, and all navigation menus. 
                        Focus ONLY on the main product details section for this specific jewelry item.
                        Extract the product title, full description text, materials/metals used, 
                        and gemstones used. Return null for images, we will extract those separately.""",
                        "schema": {
                            "type": "object",
                            "properties": {
                                "product_title": {"type": ["string", "null"]},
                                "description": {"type": ["string", "null"]},
                                "materials_text": {"type": ["string", "null"]}
                            }
                        }
                    },
                    "rawHtml"  # Request raw HTML to parse image URLs that JS hides from text extractors
                ],
                "onlyMainContent": False,
                "waitFor": 5000,
                "blockAds": True
            }
            
            scrape_resp = requests.post(f"{base_url}/scrape", headers=headers, json=scrape_payload, timeout=120)
            scrape_resp.raise_for_status()
            scrape_data = scrape_resp.json()
            
            # 1. Get perfect text from LLM
            extracted_data = scrape_data.get("data", {}).get("json", {})
            title = extracted_data.get("product_title", "")
            desc = extracted_data.get("description", "")
            materials = extracted_data.get("materials_text", "")
            text_parts = [p for p in [title, desc, materials] if p]
            text_context = "\n".join(text_parts)
            
            # 2. Extract images from Raw HTML (Bypasses LLM blindness & Python bot-blocking)
            raw_html = scrape_data.get("data", {}).get("rawHtml", "")
            clean_images = []
            seen_urls = set()
            bad_keywords = ['carprodcard', 'car2image', 'icon', 'logo', 'menu', 'sprite', 'data:image']
            
            def is_good_image(img_url):
                if not img_url or not img_url.startswith("http"): return False
                if img_url in seen_urls: return False
                if any(kw in img_url.lower() for kw in bad_keywords): return False
                # Accept standard image extensions
                if any(ext in img_url.lower() for ext in ['.jpg', '.jpeg', '.png', '.webp']): return True
                # Accept extensionless URLs with image resizing parameters
                if any(p in img_url.lower() for p in ['wid=', 'qlt=', 'imwidth=', 'imheight=']): return True
                return False

            if raw_html:
                import re as re_mod
                import json as json_mod
                
                # Strategy A: Look for JSON-LD (Schema.org) - Luxury brands usually hide gallery here
                ld_matches = re_mod.findall(r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', raw_html, re_mod.DOTALL | re_mod.IGNORECASE)
                for match in ld_matches:
                    try:
                        data = json_mod.loads(match)
                        if isinstance(data, list): data = data[0]
                        if data.get("@type") == "Product":
                            imgs = data.get("image", [])
                            if isinstance(imgs, str): imgs = [imgs]
                            for img in imgs:
                                if is_good_image(img):
                                    clean_images.append(img)
                                    seen_urls.add(img)
                    except Exception:
                        pass

                # Strategy B: If JSON-LD failed, parse standard <img src="..."> tags
                if not clean_images:
                    img_tags = re_mod.findall(r'<img[^>]+src=["\']([^"\']+)["\']', raw_html, re_mod.IGNORECASE)
                    for img in img_tags:
                        if len(clean_images) >= 5: break
                        if is_good_image(img):
                            clean_images.append(img)
                            seen_urls.add(img)

                # Strategy C: Fallback to CSS background-image (sometimes used for carousels)
                if not clean_images:
                    bg_imgs = re_mod.findall(r'background-image:\s*url\(["\']?([^"\')\s]+)["\']?\)', raw_html, re_mod.IGNORECASE)
                    for img in img_tags:
                        if len(clean_images) >= 5: break
                        if is_good_image(img):
                            clean_images.append(img)
                            seen_urls.add(img)

            output_item = {
                "url": product_page_url,
                "description": text_context,
                "images": clean_images[:5] # Max 5 images
            }

            print(json.dumps({"data": [output_item]}))

        except Exception as e:
            print(json.dumps({"data": [{"url": product_page_url, "description": "", "images": []}]}))

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