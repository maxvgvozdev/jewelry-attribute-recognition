"""
Jewelry Attribute Recognition API Service
Integrates the jewelry-attribute-recognition skill with Microsoft Business Central
via a REST API endpoint.

Run (development): uvicorn api:app --host 0.0.0.0 --port 8000 --reload
Run (production): python service_runner.py
Install as Windows service: python install_service.py install
"""

import os
import sys
import json
import logging
import tempfile
import subprocess
import traceback
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict, Any
from contextlib import asynccontextmanager

import requests
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, validator
import win32serviceutil
import win32service
import win32event
import servicemanager

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
SERVICE_NAME = "JewelryAgentAPI"
SERVICE_DISPLAY_NAME = "Jewelry Attribute Recognition API"
SERVICE_DESCRIPTION = "API service exposing jewelry attribute recognition to Microsoft Business Central"

SKILL_ROOT = Path(__file__).resolve().parent.parent
REFERENCES_DIR = SKILL_ROOT / "references"
RESULTS_DIR = SKILL_ROOT / "results"
ARTIFACTS_DIR = SKILL_ROOT / "artifacts"
FIRECRAWL_SCRIPT = SKILL_ROOT / "scripts" / "firecrawl_proxy.py"

# Ensure directories exist
RESULTS_DIR.mkdir(parents=True, exist_ok=True)
ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)

# Runtime config / env overrides
API_PORT = int(os.getenv("JEWELRY_API_PORT", "8000"))
API_HOST = os.getenv("JEWELRY_API_HOST", "0.0.0.0")
ALLOWED_ORIGINS = os.getenv("JEWELRY_API_ALLOWED_ORIGINS", "*").split(",")
LOG_LEVEL = os.getenv("JEWELRY_API_LOG_LEVEL", "INFO")


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logger = logging.getLogger(SERVICE_NAME)
logger.setLevel(getattr(logging, LOG_LEVEL.upper(), logging.INFO))

handler = logging.StreamHandler(sys.stdout)
handler.setFormatter(logging.Formatter(
    "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
))
logger.addHandler(handler)


# ---------------------------------------------------------------------------
# Pydantic models (Business Central payload / response)
# ---------------------------------------------------------------------------
class JewelryRequest(BaseModel):
    brand: str = Field(..., example="David Yurman")
    vendor_item_number: str = Field("", example="B18729D88APRDIM")
    upc_code: str = Field("", example="192740527920")
    source_url: str = Field("https://www.davidyurman.com/", example="https://www.davidyurman.com/")

    @validator("vendor_item_number", "upc_code", pre=True)
    def _empty_to_str(cls, v):
        if v is None:
            return ""
        return str(v).strip()


class ImageEvidence(BaseModel):
    url: str
    view_type: str
    alt_text: str


class LookupInfo(BaseModel):
    vendor_item_number_used: bool = False
    upc_code_used: bool = False
    cross_confirmed: bool = False


class ConfidenceInfo(BaseModel):
    overall: str = "medium"
    notes: List[str] = []


class JewelryAttributes(BaseModel):
    metal_type: Optional[str]
    metal_color: Optional[str]
    stone_primary_color: Optional[str]
    product_type: Optional[str]
    gender: Optional[str]
    center_stone_type: Optional[str]
    center_stone_shape: Optional[str]
    side_stone_1_type: Optional[str]
    side_stone_1_shape: Optional[str]
    side_stone_2_type: Optional[str]
    side_stone_2_shape: Optional[str]
    engagement_set_type: Optional[str]
    engagement_ring_type: Optional[str]
    wedding_band_type: Optional[str]
    wedding_band_setting_type: Optional[str]
    wedding_band_stone_continuity: Optional[str]
    fashion_ring_type: Optional[str]
    earring_type: Optional[str]
    necklace_type: Optional[str]
    bracelet_type: Optional[str]
    accessory_type: Optional[str]
    theme: Optional[str]
    occasion: Optional[str]
    jewelry_shape: Optional[str]
    motif: Optional[str]
    finishing_type: Optional[str]
    estate_period: Optional[str]
    holiday_code: Optional[str]
    chain_type: Optional[str]
    clasp_type: Optional[str]
    earring_back: Optional[str]


class JewelryResponse(BaseModel):
    item: Dict[str, Any]
    evidence: Dict[str, Any]
    attributes: JewelryAttributes
    lookup: LookupInfo
    confidence: ConfidenceInfo


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _firecrawl_available() -> bool:
    return FIRECRAWL_SCRIPT.exists() and FIRECRAWL_SCRIPT.is_file()


def _run_firecrawl_search(query: str) -> Dict[str, Any]:
    """Run the bundled Firecrawl proxy search and return parsed JSON."""
    if not FIRECRAWL_SCRIPT.exists():
        raise RuntimeError(f"Firecrawl proxy script not found: {FIRECRAWL_SCRIPT}")
    try:
        result = subprocess.run(
            [sys.executable, str(FIRECRAWL_SCRIPT), "search", query],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(f"Firecrawl search failed: {result.stderr}")
        return json.loads(result.stdout)
    except Exception as exc:
        logger.exception("Firecrawl search error")
        raise RuntimeError(f"Search failed: {exc}")


def _check_upc(upc_code: str) -> Dict[str, Any]:
    """Check UPC on upcitemdb.com. Returns parsed metadata or empty dict."""
    if not upc_code:
        return {}
    url = f"https://www.upcitemdb.com/upc/{upc_code}"
    try:
        resp = requests.get(url, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        html = resp.text
        # Simple heuristic check for "no record" phrase
        if "currently has no record in our database" in html:
            return {"found": False, "url": url}
        # Try to extract title from meta / heading
        import re
        title_m = re.search(r"<title>\s*UPC\s+\d+\s*-\s*(.*?)\s*\|\s*upcitemdb\.com\s*</title>", html)
        title = title_m.group(1).strip() if title_m else ""
        return {"found": bool(title), "title": title, "url": url}
    except Exception as exc:
        logger.warning("UPC check failed: %s", exc)
        return {"found": False, "error": str(exc), "url": url}


def _download_image(url: str, dest: Path) -> str:
    """Download image to artifacts dir; return absolute path."""
    try:
        resp = requests.get(url, timeout=60, headers={"User-Agent": "Mozilla/5.0"}, stream=True)
        resp.raise_for_status()
        dest.parent.mkdir(parents=True, exist_ok=True)
        with open(dest, "wb") as f:
            for chunk in resp.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    f.write(chunk)
        return str(dest)
    except Exception as exc:
        logger.error("Image download failed: %s -> %s", url, exc)
        raise


def _analyze_image(image_path: str, question: str) -> Dict[str, Any]:
    """Delegate to the local vision client."""
    from service.vision_client import analyze_image
    return analyze_image(image_path, question)


def _pick_best_images(image_urls: List[str], prefer_cdn_host: Optional[str] = None) -> List[str]:
    """Return up to 3 distinct image URLs, preferring brand CDN if host matches."""
    if not image_urls:
        return []
    if prefer_cdn_host:
        cdn = [u for u in image_urls if prefer_cdn_host in u]
        if cdn:
            return cdn[:3]
    return image_urls[:3]


def _build_attributes_from_text_and_vision(
    brand: str,
    text: str,
    vision_results: List[Dict[str, Any]],
    item_number: str,
) -> Dict[str, Any]:
    """
    Merge text + vision into the 31-parameter attribute set.
    This is intentionally simplified; extend with your reference taxonomy logic.
    """
    text_lower = (text or "").lower()
    attrs: Dict[str, Any] = {}

    # Metal
    if "yellow gold" in text_lower or "18k yellow gold" in text_lower:
        attrs["metal_type"] = "18K Yellow Gold"
        attrs["metal_color"] = "Yellow"
    elif "white gold" in text_lower or "18k white gold" in text_lower:
        attrs["metal_type"] = "18K White Gold"
        attrs["metal_color"] = "White"
    elif "rose gold" in text_lower or "18k rose gold" in text_lower:
        attrs["metal_type"] = "18K Rose Gold"
        attrs["metal_color"] = "Rose"
    else:
        attrs["metal_type"] = None
        attrs["metal_color"] = None

    # Product type heuristic
    if "bracelet" in text_lower or "bracelet" in (item_number or "").lower():
        attrs["product_type"] = "Bracelets"
    elif "ring" in text_lower or "ring" in (item_number or "").lower() or item_number.startswith(("R", "B")):
        attrs["product_type"] = "Rings"
    elif "earring" in text_lower:
        attrs["product_type"] = "Earrings"
    elif "necklace" in text_lower:
        attrs["product_type"] = "Necklaces"
    else:
        attrs["product_type"] = None

    # Gender heuristic
    if "men's" in text_lower or " men " in text_lower:
        attrs["gender"] = "Men's"
    elif "women's" in text_lower or " women " in text_lower:
        attrs["gender"] = "Women's"
    else:
        attrs["gender"] = None

    # Gemstones (very simplified)
    attrs.update({
        "stone_primary_color": None,
        "center_stone_type": None,
        "center_stone_shape": None,
        "side_stone_1_type": None,
        "side_stone_1_shape": None,
        "side_stone_2_type": None,
        "side_stone_2_shape": None,
        "engagement_set_type": None,
        "engagement_ring_type": None,
        "wedding_band_type": None,
        "wedding_band_setting_type": None,
        "wedding_band_stone_continuity": None,
        "fashion_ring_type": None,
        "earring_type": None,
        "necklace_type": None,
        "bracelet_type": None,
        "accessory_type": None,
        "theme": None,
        "occasion": None,
        "jewelry_shape": None,
        "motif": None,
        "finishing_type": None,
        "estate_period": None,
        "holiday_code": None,
        "chain_type": None,
        "clasp_type": None,
        "earring_back": None,
    })

    return attrs


# ---------------------------------------------------------------------------
# Workflow orchestration
# ---------------------------------------------------------------------------

def run_jewelry_workflow(payload: JewelryRequest) -> Dict[str, Any]:
    """
    Execute the jewelry recognition workflow end-to-end.
    Keep this in sync with the SKILL.md rules.
    """
    brand = payload.brand.strip()
    vendor_item_number = payload.vendor_item_number.strip()
    upc_code = payload.upc_code.strip()
    source_url = payload.source_url.strip()

    lookup = LookupInfo(vendor_item_number_used=bool(vendor_item_number), upc_code_used=bool(upc_code))
    confidence_notes: List[str] = []
    resolved_url = ""
    images: List[ImageEvidence] = []
    text = ""
    item_number = vendor_item_number

    # 1. UPC validation
    if upc_code:
        upc_result = _check_upc(upc_code)
        if not upc_result.get("found"):
            if not vendor_item_number:
                raise HTTPException(
                    status_code=404,
                    detail=f"UPC {upc_code} not found in UPC Item Database (upcitemdb.com).",
                )
            confidence_notes.append(
                f"UPC {upc_code} is not present in UPC Item Database; item discovery continued using vendor_item_number."
            )
        else:
            confidence_notes.append(f"UPC {upc_code} found in UPC Item Database: {upc_result.get('title', '')}")

    # 2. Item discovery: try Firecrawl first when available;
    #    otherwise fall back to source_url or upcitemdb-derived page.
    if vendor_item_number:
        search_query = f"{brand} {vendor_item_number}"
    elif upc_code:
        search_query = f"{brand} {upc_code}"
    else:
        raise HTTPException(status_code=400, detail="Either vendor_item_number or upc_code must be provided.")

    items = []
    resolved_url = ""

    firecrawl_available = _firecrawl_available()
    if firecrawl_available:
        try:
            search_result = _run_firecrawl_search(search_query)
            items = search_result.get("data", []) or []
            if items:
                resolved_url = items[0].get("url", "")
                page_text = items[0].get("description", "") or ""
        except Exception as exc:
            firecrawl_available = False
            confidence_notes.append(f"Firecrawl search unavailable; using direct HTTP fallback only. ({exc})")
    else:
        confidence_notes.append("Firecrawl is not configured; using direct HTTP fallback only.")

    if not resolved_url:
        if source_url:
            resolved_url = source_url
        elif upc_code:
            resolved_url = f"https://www.upcitemdb.com/upc/{upc_code}"
        else:
            raise HTTPException(status_code=404, detail="No product pages available for the provided identifiers.")

    # 3. Try to scrape the resolved page for richer text and images
    page_text = ""
    image_urls: List[str] = []
    try:
        from urllib.parse import urlparse
        parsed = urlparse(resolved_url)
        host = parsed.hostname or ""
    except Exception:
        host = ""

    if resolved_url:
        try:
            page_resp = requests.get(resolved_url, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
            page_resp.raise_for_status()
            html = page_resp.text
            page_text = f"{items[0].get('title', '')} {items[0].get('description', '')} {html[:2000]}"
            # Very naive image extraction
            import re
            image_urls = re.findall(r"https?://[^\s\"'>]+\.(?:jpg|jpeg|png)", html)
        except Exception as exc:
            logger.warning("Page scrape failed: %s", exc)
            confidence_notes.append(f"Direct page scrape failed for {resolved_url}; using search snippet only.")
            page_text = f"{items[0].get('title', '')} {items[0].get('description', '')}"

    # 4. Download images and run vision analysis
    chosen = _pick_best_images(image_urls, prefer_cdn_host="davidyurman" if "davidyurman" in host else None)
    if not chosen:
        confidence_notes.append("No downloadable images found from resolved page; attributes may be text-only.")

    vision_results: List[Dict[str, Any]] = []
    for idx, img_url in enumerate(chosen[:3], start=1):
        view_map = {1: "front", 2: "side", 3: "additional"}
        view_type = view_map.get(idx, "additional")
        local_name = ARTIFACTS_DIR / f"svc_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{idx}.jpg"
        try:
            local_path = _download_image(img_url, local_name)
            vision = _analyze_image(local_path, f"{view_type} view analysis for {brand} {item_number}")
            vision_results.append(vision)
            images.append(
                ImageEvidence(
                    url=img_url,
                    view_type=view_type,
                    alt_text=f"{view_type.title()} view of {brand} {item_number or upc_code}",
                )
            )
        except Exception as exc:
            logger.warning("Image handling failed for %s: %s", img_url, exc)

    # 5. Build attributes
    combined_text = f"{page_text} {' '.join(v.get('analysis','') for v in vision_results)}"
    attrs_dict = _build_attributes_from_text_and_vision(brand, combined_text, vision_results, item_number or upc_code)

    # 6. Package response
    response = {
        "item": {
            "brand": brand,
            "vendor_item_number": vendor_item_number,
            "upc_code": upc_code,
            "source_url": source_url,
            "resolved_item_url": resolved_url,
        },
        "evidence": {
            "images": [img.dict() for img in images],
            "text": combined_text[:2000],
        },
        "attributes": attrs_dict,
        "lookup": lookup.dict(),
        "confidence": {
            "overall": "high" if images else "low",
            "notes": confidence_notes,
        },
    }
    return response


# ---------------------------------------------------------------------------
# FastAPI application
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Jewelry Agent API starting up on %s:%s", API_HOST, API_PORT)
    yield
    logger.info("Jewelry Agent API shutting down")


app = FastAPI(
    title="Jewelry Attribute Recognition API",
    description="Exposes jewelry recognition workflow for Microsoft Business Central",
    version="1.0.0",
    lifespan=lifespan,
)


@app.get("/health")
async def health():
    return {"status": "ok", "service": SERVICE_NAME}


@app.post("/api/jewelry/recognize", response_model=JewelryResponse)
async def recognize(req: JewelryRequest):
    logger.info("Received jewelry request: brand=%s, vendor=%s, upc=%s", req.brand, req.vendor_item_number, req.upc_code)
    try:
        result = run_jewelry_workflow(req)
        return JSONResponse(content=result)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Workflow failed")
        raise HTTPException(status_code=500, detail=f"Internal error: {exc}")


# ---------------------------------------------------------------------------
# Windows Service wrapper
# ---------------------------------------------------------------------------

class JewelryAPIService(win32serviceutil.ServiceFramework):
    _svc_name_ = SERVICE_NAME
    _svc_display_name_ = SERVICE_DISPLAY_NAME
    _svc_description_ = SERVICE_DESCRIPTION

    def __init__(self, args):
        win32serviceutil.ServiceFramework.__init__(self, args)
        self.stop_event = win32event.CreateEvent(None, 0, 0, None)
        self.worker: Optional[subprocess.Popen] = None

    def SvcStop(self):
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        if self.worker:
            self.worker.terminate()
        win32event.SetEvent(self.stop_event)

    def SvcDoRun(self):
        servicemanager.LogMsg(
            servicemanager.EVENTLOG_INFORMATION_TYPE,
            servicemanager.PYS_SERVICE_STARTED,
            (self._svc_name_, ""),
        )
        logger.info("Windows service starting")
        cmd = [
            sys.executable, "-m", "uvicorn",
            "service.api:app",
            "--host", API_HOST,
            "--port", str(API_PORT),
            "--log-level", LOG_LEVEL.lower(),
        ]
        self.worker = subprocess.Popen(cmd, cwd=str(SKILL_ROOT))
        win32event.WaitForSingleObject(self.stop_event, win32event.INFINITE)
        logger.info("Windows service stopped")


if __name__ == "__main__":
    if len(sys.argv) == 1:
        # Run as console app for debugging
        import uvicorn
        uvicorn.run(app, host=API_HOST, port=API_PORT, log_level=LOG_LEVEL.lower())
    else:
        win32serviceutil.HandleCommandLine(JewelryAPIService)
