import os
import sys
import json
import urllib.request
import urllib.error

API_KEY = os.environ.get("FIRECRAWL_API_KEY", "").strip()
BASE = "https://api.firecrawl.dev/v1"

if not API_KEY:
    here = os.path.dirname(os.path.abspath(__file__))
    skill_root = os.path.abspath(os.path.join(here, ".."))
    cfg = os.path.join(skill_root, "firecrawl_config.json")
    if os.path.exists(cfg):
        with open(cfg, "r", encoding="utf-8") as f:
            data = json.load(f)
            API_KEY = (data.get("api_key") or "").strip()
    if not API_KEY:
        print("Set FIRECRAWL_API_KEY env var or create firecrawl_config.json with { \"api_key\": \"...\" }", file=sys.stderr)
        sys.exit(2)

def call(method, path, payload=None):
    url = BASE + path
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {API_KEY}")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        print(f"HTTP {e.code}: {body}", file=sys.stderr)
        sys.exit(1)

def search(query, limit=10):
    return call("POST", "/search", {"query": query, "limit": limit, "timeout": 30000})

def scrape(url, formats=None):
    if formats is None:
        formats = ["markdown"]
    return call("POST", "/scrape", {"url": url, "formats": formats, "onlyMainContent": True, "timeout": 30000})

def crawl(url, limit=10):
    return call("POST", "/crawl", {"url": url, "limit": limit, "maxDepth": 2, "allowedDomains": [], "timeout": 60000})

def main():
    if len(sys.argv) < 2:
        print("Commands: search <query> | scrape <url> | crawl <url> [limit]", file=sys.stderr)
        sys.exit(1)
    cmd = sys.argv[1]
    if cmd == "search" and len(sys.argv) >= 3:
        q = sys.argv[2]
        limit = int(sys.argv[3]) if len(sys.argv) > 3 else 10
        print(json.dumps(search(q, limit), ensure_ascii=False, indent=2))
    elif cmd == "scrape" and len(sys.argv) >= 3:
        print(json.dumps(scrape(sys.argv[2]), ensure_ascii=False, indent=2))
    elif cmd == "crawl" and len(sys.argv) >= 3:
        limit = int(sys.argv[3]) if len(sys.argv) > 3 else 10
        print(json.dumps(crawl(sys.argv[2], limit), ensure_ascii=False, indent=2))
    else:
        print(f"Usage: firecrawl_proxy.py search <query> | scrape <url> | crawl <url> [limit]", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
