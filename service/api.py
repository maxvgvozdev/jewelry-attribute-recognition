"""
Jewelry Attribute Recognition API Service
Integrates the jewelry-attribute-recognition skill with Microsoft Business Central
via a REST API endpoint.

Run (development): uvicorn api:app --host 0.0.0.0 --port 8000 --reload
Run (production via Task Scheduler): python.exe api.py
"""

import os
import sys
import json
import logging
import re
import tempfile
import subprocess
import traceback
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict, Any
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse

import requests
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field, field_validator

try:
    import uvicorn as _uvicorn
except Exception:
    _uvicorn = None

# Strict schema prompt for Vision AI to extract all 31 BC365 fields
from config import VISION_EXTRACTION_PROMPT

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
SERVICE_NAME = "JewelryAgentAPI"
SERVICE_DISPLAY_NAME = "Jewelry Attribute Recognition API"
SERVICE_DESCRIPTION = "API service exposing jewelry attribute recognition to Microsoft Business Central"

SKILL_ROOT = Path(__file__).resolve().parent.parent
ARTIFACTS_DIR = SKILL_ROOT / "artifacts"
FIRECRAWL_SCRIPT = SKILL_ROOT / "scripts" / "firecrawl_proxy.py"

# Ensure repo root is on sys.path so package imports like `from service.vision_client import ...`
# resolve correctly when launched by Task Scheduler.
if str(SKILL_ROOT) not in sys.path:
    sys.path.insert(0, str(SKILL_ROOT))

# Ensure artifacts directory exists
ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)

# Runtime config / env overrides
API_PORT = int(os.getenv("JEWELRY_API_PORT", "8000"))
API_HOST = os.getenv("JEWELRY_API_HOST", "0.0.0.0")
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
    brand: str = Field(..., json_schema_extra={"examples": ["David Yurman"]})
    vendor_item_number: str = Field("", json_schema_extra={"examples": ["B18729D88APRDIM"]})
    upc_code: str = Field("", json_schema_extra={"examples": ["192740527920"]})
    source_url: str = Field("", json_schema_extra={"examples": ["https://www.cartier.com/"]})

    @field_validator("vendor_item_number", "upc_code", mode="before")
    @classmethod
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
        if "currently has no record in our database" in html:
            return {"found": False, "url": url}
        title_m = re.search(r"<title>\s*UPC\s+\d+\s*-\s*(.*?)\s*\|\s*upcitemdb\.com\s*</title>", html)
        title = title_m.group(1).strip() if title_m else ""
        return {"found": bool(title), "title": title, "url": url}
    except Exception as exc:
        logger.warning("UPC check failed: %s", exc)
        return {"found": False, "error": str(exc), "url": url}


def _download_image(url: str, dest: Path, referer: str = "") -> str:
    """Download image to artifacts dir; return absolute path."""
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        # Bypass hotlink protection (CDN 403s) by pretending to be the brand's own webpage
        if referer:
            headers["Referer"] = referer
            
        # CRITICAL FIX: Use tuple (connect_timeout, read_timeout).
        resp = requests.get(url, timeout=(10, 30), headers=headers, stream=True)
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


def _extract_json_from_text(text: str) -> Optional[Dict[str, Any]]:
    """Extracts a JSON object from text, even if surrounded by reasoning or markdown."""
    if not text:
        return None
        
    # 1. Try to find a JSON code block ```json ... ```
    json_block_match = re.search(r'```json\s*(\{.*?\})\s*```', text, re.DOTALL | re.IGNORECASE)
    if json_block_match:
        try:
            return json.loads(json_block_match.group(1))
        except json.JSONDecodeError:
            pass

    # 2. Fallback: Find the first '{' and the very last '}' in the entire text.
    first_brace = text.find('{')
    last_brace = text.rfind('}')
    
    if first_brace != -1 and last_brace > first_brace:
        json_str = text[first_brace : last_brace + 1]
        try:
            return json.loads(json_str)
        except json.JSONDecodeError:
            pass

    return None


def _build_attributes_from_text_and_vision(
    brand: str,
    text: str,
    vision_results: List[Dict[str, Any]],
    item_number: str,
) -> Dict[str, Any]:
    text_lower = (text or "").lower()
    
    # 1. Initialize all 31 fields as null
    attrs = {
        "metal_type": None, "metal_color": None, "stone_primary_color": None,
        "product_type": None, "gender": None, "center_stone_type": None,
        "center_stone_shape": None, "side_stone_1_type": None, "side_stone_1_shape": None,
        "side_stone_2_type": None, "side_stone_2_shape": None, "engagement_set_type": None,
        "engagement_ring_type": None, "wedding_band_type": None, "wedding_band_setting_type": None,
        "wedding_band_stone_continuity": None, "fashion_ring_type": None, "earring_type": None,
        "necklace_type": None, "bracelet_type": None, "accessory_type": None,
        "theme": None, "occasion": None, "jewelry_shape": None, "motif": None,
        "finishing_type": None, "estate_period": None, "holiday_code": None,
        "chain_type": None, "clasp_type": None, "earring_back": None,
    }

    # 2. Try to parse the JSON returned by the Vision AI
    for v_res in vision_results:
        analysis_text = v_res.get("analysis", "")
        if not analysis_text:
            continue
            
        # Use the JSON hunter to find the object, bypassing any reasoning text
        vision_attrs = _extract_json_from_text(analysis_text)
        
        if vision_attrs and isinstance(vision_attrs, dict):
            # Only update attrs if the vision AI found a non-null value
            for key, value in vision_attrs.items():
                if key in attrs and value is not None:
                    attrs[key] = value

    # 3. Text-based overrides (Text is more reliable for exact metal karats and explicit specs)
    if "18k yellow gold" in text_lower or "18-karat yellow gold" in text_lower:
        attrs["metal_type"] = "18K Yellow Gold"
        attrs["metal_color"] = "Yellow"
    elif "18k white gold" in text_lower or "18-karat white gold" in text_lower:
        attrs["metal_type"] = "18K White Gold"
        attrs["metal_color"] = "white"  # Fixed casing to match BC365 schema
    elif "18k rose gold" in text_lower or "18-karat rose gold" in text_lower:
        attrs["metal_type"] = "18K Rose Gold"
        attrs["metal_color"] = "Rose"

    if "platinum" in text_lower:
        attrs["metal_type"] = "Platinum"
        attrs["metal_color"] = "White"

    if "diamond" in text_lower and attrs.get("center_stone_type") is None:
        attrs["center_stone_type"] = "Diamond"

    return attrs


# ---------------------------------------------------------------------------
# Workflow orchestration
# ---------------------------------------------------------------------------

def run_jewelry_workflow(payload: JewelryRequest) -> Dict[str, Any]:
    brand = payload.brand.strip()
    vendor_item_number = payload.vendor_item_number.strip()
    upc_code = payload.upc_code.strip()
    source_url = payload.source_url.strip()

    lookup = LookupInfo(vendor_item_number_used=bool(vendor_item_number), upc_code_used=bool(upc_code))
    confidence_notes: List[str] = []
    resolved_url = ""
    images: List[ImageEvidence] = []
    page_text = ""
    item_number = vendor_item_number

    if upc_code:
        upc_result = _check_upc(upc_code)
        if not upc_result.get("found"):
            if not vendor_item_number:
                raise HTTPException(status_code=404, detail=f"UPC {upc_code} not found in UPC Item Database (upcitemdb.com).")
            confidence_notes.append(f"UPC {upc_code} is not present in UPC Item Database; item discovery continued using vendor_item_number.")
        else:
            confidence_notes.append(f"UPC {upc_code} found in UPC Item Database: {upc_result.get('title', '')}")

    if vendor_item_number:
        search_query = f"{brand} {vendor_item_number}"
    elif upc_code:
        search_query = f"{brand} {upc_code}"
    else:
        raise HTTPException(status_code=400, detail="Either vendor_item_number or upc_code must be provided.")

    image_urls = []
    
    if _firecrawl_available():
        try:
            search_result = _run_firecrawl_search(search_query)
            items = search_result.get("data", []) or []
            if items:
                resolved_url = items[0].get("url", "")
                page_text = items[0].get("description", "") or ""
                
                firecrawl_images = items[0].get("images", [])
                if firecrawl_images:
                    image_urls = firecrawl_images
                    confidence_notes.append("Extracted product data and images via Firecrawl V2.")
                else:
                    confidence_notes.append("Firecrawl V2 extracted text, but 0 images.")
                    
        except Exception as exc:
            confidence_notes.append(f"Firecrawl proxy failed; using direct HTTP fallback only. ({exc})")
    else:
        confidence_notes.append("Firecrawl is not configured; using direct HTTP fallback only.")

    if not resolved_url:
        if source_url:
            resolved_url = source_url
        elif upc_code:
            resolved_url = f"https://www.upcitemdb.com/upc/{upc_code}"
        else:
            raise HTTPException(status_code=404, detail="No product pages available for the provided identifiers.")

    # Get host for CDN preference logic
    try:
        from urllib.parse import urlparse
        parsed = urlparse(resolved_url)
        host = parsed.hostname or ""
    except Exception:
        host = ""

    vision_results: List[Dict[str, Any]] = []
    for idx, img_url in enumerate(image_urls[:3], start=1):
        view_map = {1: "front", 2: "side", 3: "additional"}
        view_type = view_map.get(idx, "additional")
        local_name = ARTIFACTS_DIR / f"svc_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{idx}.jpg"
        try:
            local_path = _download_image(img_url, local_name, referer=resolved_url)
            vision = _analyze_image(local_path, VISION_EXTRACTION_PROMPT)
            vision_results.append(vision)
            images.append(ImageEvidence(url=img_url, view_type=view_type, alt_text=f"{view_type.title()} view of {brand} {item_number or upc_code}"))
        except Exception as exc:
            error_msg = f"Image processing/analysis failed for {img_url}: {exc}"
            logger.warning(error_msg)
            confidence_notes.append(error_msg)

    combined_text = f"{page_text} {' '.join(v.get('analysis','') for v in vision_results)}"
    attrs_dict = _build_attributes_from_text_and_vision(brand, combined_text, vision_results, item_number or upc_code)

    return {
        "item": {"brand": brand, "vendor_item_number": vendor_item_number, "upc_code": upc_code, "source_url": source_url, "resolved_item_url": resolved_url},
        "evidence": {"images": [img.dict() for img in images], "text": combined_text[:2000]},
        "attributes": attrs_dict,
        "lookup": lookup.dict(),
        "confidence": {"overall": "high" if images else "low", "notes": confidence_notes},
    }


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
        return result  # FastAPI validates against JewelryResponse automatically
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Workflow failed")
        raise HTTPException(status_code=500, detail=f"Internal error: {exc}")


# ---------------------------------------------------------------------------
# Windows Service wrapper
# ---------------------------------------------------------------------------
# NOTE: Currently disabled. We are using Task Scheduler running "python.exe api.py" instead
# because the .venv pythonservice.exe had DLL registration issues on this server.
# To re-enable: 
#   1. Install pywin32 globally or fix the .venv pywin32_postinstall.py -install (as Admin)
#   2. Change Task Scheduler action to use the .venv\pythonservice.exe
#   3. Change this if __name__ block to: if len(sys.argv) > 1: win32serviceutil.HandleCommandLine(JewelryAPIService)
# ---------------------------------------------------------------------------
try:
    import win32serviceutil
    import win32service
    import win32event
    import servicemanager
except ImportError:
    pass # pywin32 is not installed on this machine

class JewelryAPIService(win32serviceutil.ServiceFramework):
    _svc_name_ = SERVICE_NAME
    _svc_display_name_ = SERVICE_DISPLAY_NAME
    _svc_description_ = SERVICE_DESCRIPTION

    def __init__(self, args):
        win32serviceutil.ServiceFramework.__init__(self, args)
        self.stop_event = win32event.CreateEvent(None, 0, 0, None)
        self._uvicorn_server = None

    def SvcStop(self):
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        if self._uvicorn_server is not None:
            self._uvicorn_server.should_exit = True
        win32event.SetEvent(self.stop_event)

    def SvcDoRun(self):
        try:
            service_dir = Path(__file__).resolve().parent
            os.chdir(service_dir)
            if service_dir not in sys.path:
                sys.path.insert(0, str(service_dir))

            if _uvicorn is None:
                raise RuntimeError("uvicorn could not be imported.")

            servicemanager.LogMsg(
                servicemanager.EVENTLOG_INFORMATION_TYPE,
                servicemanager.PYS_SERVICE_STARTED,
                (self._svc_name_, ""),
            )
            self.ReportServiceStatus(win32service.SERVICE_RUNNING)
            logger.info("Windows service started, launching uvicorn")

            config = _uvicorn.Config(app, host=API_HOST, port=API_PORT, log_level=LOG_LEVEL.lower())
            self._uvicorn_server = _uvicorn.Server(config)
            self._uvicorn_server.run()

        except Exception as exc:
            tb = traceback.format_exc()
            try:
                servicemanager.LogErrorMsg(f"Service failed: {exc}\n{tb}")
            except Exception:
                pass
            logger.exception("Windows service failed to start: %s", exc)
            self.ReportServiceStatus(win32service.SERVICE_STOPPED, win32service.SERVICE_ERROR_SEVERE)
            raise

if __name__ == "__main__":
    if len(sys.argv) == 1:
        import uvicorn
        uvicorn.run(app, host=API_HOST, port=API_PORT, log_level=LOG_LEVEL.lower())
    else:
        try:
            win32serviceutil.HandleCommandLine(JewelryAPIService)
        except Exception:
            # Fallback to standard uvicorn run if pywin32 is not installed
            import uvicorn
            uvicorn.run(app, host=API_HOST, port=API_PORT, log_level=LOG_LEVEL.lower())