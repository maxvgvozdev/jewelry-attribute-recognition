"""
Firecrawl proxy script.
Usage: python firecrawl_proxy.py search "<query>"
Requires FIRECRAWL_API_KEY environment variable.
"""
import sys
import json
import os
import requests

def main():
    if len(sys.argv) < 3:
        print(json.dumps({"error": "Usage: python firecrawl_proxy.py search <query>"}))
        sys.exit(1)

    command = sys.argv[1]
    query = sys.argv[2]
    api_key = os.getenv("FIRECRAWL_API_KEY")

    if not api_key:
        print(json.dumps({"error": "Set FIRECRAWL_API_KEY env var or create firecrawl_config.json with { \"api_key\": \"...\" }\n"}))
        sys.exit(1)

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    base_url = "https://api.firecrawl.dev/v1"

    if command == "search":
        # Step 1: Search for the product page
        search_payload = {"query": query, "limit": 1}
        try:
            search_resp = requests.post(f"{base_url}/search", headers=headers, json=search_payload, timeout=60)
            search_resp.raise_for_status()
        except Exception as e:
            print(json.dumps({"error": f"Firecrawl search failed: {str(e)}"}))
            sys.exit(1)
            
        search_data = search_resp.json()
        
        if not search_data.get("data"):
            print(json.dumps({"data": []}))
            return

        top_result = search_data["data"][0]
        target_url = top_result.get("url")

        if not target_url:
            print(json.dumps({"data": [top_result]}))
            return

        # Step 2: Scrape the specific page with waitFor to render JS lazy-loaded images
        scrape_payload = {
            "url": target_url,
            "waitFor": 3000, # Wait 3 seconds for JavaScript to load images
            "actions": [
                {"type": "wait", "milliseconds": 3000}
            ]
        }
        
        try:
            scrape_resp = requests.post(f"{base_url}/scrape", headers=headers, json=scrape_payload, timeout=120)
            scrape_resp.raise_for_status()
            scrape_data = scrape_resp.json()
            
            # Extract the fully rendered HTML
            rendered_html = scrape_data.get("data", {}).get("html", "")
            
            # Attach the rendered HTML to our search result so api.py can use it
            top_result["rendered_html"] = rendered_html
            
        except Exception as e:
            # If scrape fails, just return the basic search result
            pass

        # Output the final JSON for api.py to consume
        print(json.dumps({"data": [top_result]}))

if __name__ == "__main__":
    main()