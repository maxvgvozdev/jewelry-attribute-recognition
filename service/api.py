"""
Jewelry & Watch Attribute Recognition API Service
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
from typing import Optional, List, Dict, Any, Union
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse

import requests
from fastapi import FastAPI, HTTPException, File, UploadFile, Form
from pydantic import BaseModel, Field, field_validator

try:
    import uvicorn as _uvicorn
except Exception:
    _uvicorn = None

# Strict schema prompts for Vision AI to extract BC365 fields
from config import VISION_EXTRACTION_PROMPT, WATCH_VISION_EXTRACTION_PROMPT

# Ensure repo root is on sys.path so package imports like `from service.vision_client import ...`
# resolve correctly when launched by Task Scheduler.
SKILL_ROOT = Path(__file__).resolve().parent.parent
if str(SKILL_ROOT) not in sys.path:
    sys.path.insert(0, str(SKILL_ROOT))

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
SERVICE_NAME = "JewelryAgentAPI"
SERVICE_DISPLAY_NAME = "Jewelry Attribute Recognition API"
SERVICE_DESCRIPTION = "API service exposing jewelry & watch attribute recognition to Microsoft Business Central"

ARTIFACTS_DIR = SKILL_ROOT / "artifacts"
FIRECRAWL_SCRIPT = SKILL_ROOT / "scripts" / "firecrawl_proxy.py"

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
    category: str = Field("jewelry", json_schema_extra={"examples": ["jewelry", "watch"]})
    brand: str = Field(..., json_schema_extra={"examples": ["David Yurman"]})
    vendor_item_number: str = Field("", json_schema_extra={"examples": ["B18729D88APRDIM"]})
    upc_code: str = Field("", json_schema_extra={"examples": ["192740527920"]})
    source_url: str = Field("", json_schema_extra={"examples": ["https://www.cartier.com/"]})
    
    pre_filled_attributes: Optional[Dict[str, Any]] = Field(None, description="Attributes pre-extracted from invoice")

    @field_validator("vendor_item_number", "upc_code", "source_url", mode="before")
    @classmethod
    def _empty_to_str(cls, v):
        if v is None: return ""
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

class WatchAttributes(BaseModel):
    functions_complications: Optional[str]
    watch_style: Optional[str]
    movement_type: Optional[str]
    display_type: Optional[str]
    case_diameter: Optional[str]
    case_thickness_mm: Optional[str]
    case_shape: Optional[str]
    dial_color: Optional[str]
    case_back: Optional[str]
    dial_motif: Optional[str]
    watch_display_number_type: Optional[str]
    dial_embellishment: Optional[str]
    case_material: Optional[str]
    strap_bracelet_type: Optional[str]
    strap_bracelet_material: Optional[str]
    case_color: Optional[str]
    strap_color: Optional[str]
    strap_secondary_color: Optional[str]
    strap_bracelet_width_mm: Optional[str]
    crystal_material: Optional[str]
    special_functions: Optional[str]
    power_reserve_hour: Optional[str]
    water_resistance_m: Optional[str]
    clasp_type: Optional[str]
    watch_brand: Optional[str]
    watch_collection: Optional[str]
    bezel_type: Optional[str]
    winding_crown: Optional[str]
    calibre: Optional[str]
    precision: Optional[str]
    certification: Optional[str]
    gender: Optional[str]
    msrp_price: Optional[str]
    year_produced: Optional[str]
    limited_production: Optional[str]
    watch_size: Optional[str]
    treatment: Optional[str]

class InvoiceLineItem(BaseModel):
    sku: Optional[str] = None
    sku_alternate: Optional[str] = None
    description: Optional[str] = None
    brand: Optional[str] = None
    qty: Optional[float] = None
    unit: Optional[str] = None
    weight: Optional[float] = None
    unit_price: Optional[float] = None
    price: Optional[float] = None
    price_basis: Optional[str] = None
    attributes: Optional[Dict[str, Any]] = None 

class InvoiceResponse(BaseModel):
    vendor_name: Optional[str] = None
    invoice_number: Optional[str] = None
    invoice_date: Optional[str] = None
    currency: Optional[str] = None
    line_items: List[InvoiceLineItem] = []
    subtotal: Optional[float] = None
    freight: Optional[float] = None
    total: Optional[float] = None
    needs_review: bool = False
    review_reason: Optional[str] = None

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _firecrawl_available() -> bool:
    return FIRECRAWL_SCRIPT.exists() and FIRECRAWL_SCRIPT.is_file()

def _run_firecrawl_search(query: str) -> Dict[str, Any]:
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

def _run_firecrawl_scrape(url: str) -> Dict[str, Any]:
    if not FIRECRAWL_SCRIPT.exists():
        raise RuntimeError(f"Firecrawl proxy script not found: {FIRECRAWL_SCRIPT}")
    try:
        result = subprocess.run(
            [sys.executable, str(FIRECRAWL_SCRIPT), "scrape", url],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(f"Firecrawl scrape failed: {result.stderr}")
        return json.loads(result.stdout)
    except Exception as exc:
        raise RuntimeError(f"Scrape failed: {exc}")

def _check_upc(upc_code: str) -> Dict[str, Any]:
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
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        if referer:
            headers["Referer"] = referer
            
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
    from service.vision_client import analyze_image
    return analyze_image(image_path, question)

def _extract_json_from_text(text: str) -> Optional[Dict[str, Any]]:
    """Extracts a JSON object from text, even if surrounded by reasoning, markdown, or truncated."""
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

    # 3. NEW FALLBACK: Handle truncated JSON (missing closing brace)
    if first_brace != -1:
        # Grab everything from the first '{' to the end of the text
        truncated_json = text[first_brace:]
        # Strip trailing commas and whitespace that cause JSON errors
        truncated_json = truncated_json.rstrip().rstrip(',')
        # Append the missing closing brace
        repaired_json = truncated_json + '}'
        
        try:
            return json.loads(repaired_json)
        except json.JSONDecodeError:
            # If it's still broken (e.g., missing a value at the very end like `"color": `), 
            # try removing the last incomplete key-value pair
            try:
                # Find the last comma and cut it off there, then close the brace
                last_comma = repaired_json.rfind(',')
                if last_comma != -1:
                    fixed_json = repaired_json[:last_comma] + '}'
                    return json.loads(fixed_json)
            except Exception:
                pass

    return None

import fitz  # PyMuPDF
import base64

INVOICE_VISION_MODEL = os.getenv("INVOICE_VISION_MODEL", "default:latest")

INVOICE_VISION_PROMPT = """You are a precise invoice data extraction engine.
You will receive one or more scanned invoice page images. Read only what is visually present.
Your task is to extract purchased product line items and invoice totals.
Do not extract legal text, payment terms, shipping terms, warranty statements, destination control statements, batch/receipt stamps, tracking numbers, purchase order numbers, sales order numbers, customer numbers, or parcel numbers as product line items.

For each purchased product line item, extract:
- sku: Vendor product identifier (Article, Item, Style, SKU). Do not use PO/SO/Tracking numbers.
- sku_alternate: Second product code linked to the same line (e.g., packing-list code). Null if absent.
- description: Clean product description. Normalize line breaks to spaces.
- brand: The specific brand or manufacturer of the item (e.g., Herco, David Yurman, Cartier). Infer from the description if necessary. Null if not present.
- category: Must be either "jewelry" or "watch". Use "watch" if the item is a timepiece.
- qty: Numeric quantity. Null if missing.
- unit: Unit of measure (PC, GM, EA). Null if absent.
- weight: Numeric line weight. Null if absent.
- unit_price: Numeric unit price. Use wholesale/invoice price if both retail and wholesale are shown.
- price: Numeric amount charged for the line (extended price).
- price_basis: "per_piece", "per_gram", "per_line", or "unknown".

Also extract invoice-level fields: vendor_name, invoice_number, invoice_date (YYYY-MM-DD), currency, subtotal, freight, total.
Number rules: Remove thousands separators, use plain JSON numbers, period as decimal. Do not invent values. Use null for missing/illegible.

Return ONLY one valid JSON object. No Markdown, no code fences, no explanations.
Shape:
{
  "vendor_name": null, "invoice_number": null, "invoice_date": null, "currency": null,
  "line_items": [
    {"sku": null, "sku_alternate": null, "description": null, "brand": null, "category": "jewelry", "qty": null, "unit": null, "weight": null, "unit_price": null, "price": null, "price_basis": null}
  ],
  "subtotal": null, "freight": null, "total": null, "needs_review": false, "review_reason": null
}"""

def _render_pdf_to_images(file_path: str, dpi: int = 150) -> List[str]:
    doc = fitz.open(file_path)
    images_b64 = []
    zoom = dpi / 72
    mat = fitz.Matrix(zoom, zoom)
    
    price_pattern = re.compile(r'\$\s*\d+\.\d{2}|\d+\.\d{2}')
    legal_pattern = re.compile(r'(terms\s*&\s*conditions|warranty|governing law|liability|force majeure|intellectual property rights|return of non-defective)', re.IGNORECASE)

    for page in doc:
        text = page.get_text("text")
        
        if text.strip():
            if legal_pattern.search(text):
                logger.info(f"Skipping page {page.number + 1} (detected Terms & Conditions / legal text).")
                continue
            price_matches = len(price_pattern.findall(text))
            if price_matches < 2:
                logger.info(f"Skipping page {page.number + 1} (no item prices detected).")
                continue

        pix = page.get_pixmap(matrix=mat)
        img_bytes = pix.tobytes("jpeg")
        b64 = base64.b64encode(img_bytes).decode("utf-8")
        images_b64.append(b64)
        
        if len(images_b64) >= 2:
            logger.info("Reached 2 page limit for Vision AI. Stopping page extraction.")
            break
        
    doc.close()
    
    if not images_b64 and len(doc) > 0:
        for i in range(min(2, len(doc))):
            page = doc[i]
            pix = page.get_pixmap(matrix=mat)
            img_bytes = pix.tobytes("jpeg")
            b64 = base64.b64encode(img_bytes).decode("utf-8")
            images_b64.append(b64)
            
    return images_b64

def _ask_vision_llm_for_invoice(images_b64: List[str]) -> Dict[str, Any]:
    from service.vision_client import VISION_API_URL
    
    payload = {
        "model": INVOICE_VISION_MODEL,
        "messages": [
            {
                "role": "user",
                "content": INVOICE_VISION_PROMPT,
                "images": images_b64
            }
        ],
        "stream": False,
        "format": "json",
        "options": {
            "temperature": 0,
            "num_ctx": 32768,
            "num_predict": 4096
        }
    }
    
    url = f"{VISION_API_URL}/api/chat"
    logger.info(f"Sending {len(images_b64)} invoice page(s) to {INVOICE_VISION_MODEL} on spark...")
    resp = requests.post(url, json=payload, timeout=600) 
    resp.raise_for_status()
    
    data = resp.json()
    raw_content = data.get("message", {}).get("content", "")
    return _extract_json_from_text(raw_content) or {}

# ---------------------------------------------------------------------------
# BC365 Master Data Strict Schema Mapping
# ---------------------------------------------------------------------------

VALID_BC365_OPTIONS: Dict[str, set] = {
    "metal_type": {
        "09K", "10K", "10KGF", "12K", "14K", "14KGF", "18K", "19K", "22K", "24K", 
        "950PAL", "950PL", "Cobalt", "Crystal", "Enamel", "Enhancers", "Glass", 
        "Goldplated", "Leather", "Rubber", "Silicone", "STSILVER", "STSILVER/14K", 
        "STSILVER/18K", "STSILVER/STSTEEL", "STSTEEL", "Steel/18K", "Wood", 
        "Argentium Silver", "Pewter", "Silver Plated"
    },
    "metal_color": {
        "Black", "Black/Yellow", "GREY", "White", "Yellow", "Yellow/White", 
        "Yellow/White/Rose", "Rose", "Rose/White"
    },
    "stone_primary_color": {
        "Black", "Blue", "Brown", "Dark Blue", "Golden", "Green", "Grey", 
        "Multicolor", "Navy", "Orange", "Pink", "Purple", "Red", "Silver", 
        "Turquoise", "White", "Yellow", "Aqua", "Light Blue"
    },
    "product_type": {
        "Accessories", "Amulet-Mens", "Anklets", "Bracelets", "Charms", "Earrings", 
        "Engagement Rings", "Engagement Set", "Fashion Rings", "Jewelry Sets", 
        "Necklaces", "Wedding Bands", "Chain", "Engagement Semimounting", "Other", 
        "Pin/Brooch", "Enhancers"
    },
    "gender": {"Baby", "Gents", "Ladies", "Unisex"},
    "center_stone_type": {
        "Abalone", "Agate", "Akoya Pearl", "Akoya white pearls", "Alexandrite", 
        "Amazonite", "Amethyst", "Aquamarine", "Azurite", "Black Diamond", 
        "Black Freshwater Pearl", "Black mother of pearl", "Black Onyx", 
        "Black orchid", "Black spinel", "Black South Sea Pearl", "Blue Chalcedony", 
        "Blue Diamond", "Blue Sapphire", "Blue Topaz", "Brown Diamond", "Carnelian", 
        "Champagne citrine", "Champagne Diamond", "Charoite", "Chinese turquoise", 
        "CHRYSOCOLLA", "Chrysoprase", "Citrine", "Cognac Diamonds", 
        "Color Change Garnet", "Coral", "Corundum", "Crystal", 
        "Cultured freshwater pearls", "Cultured Pearl", "CZ", "Diamond", "Emerald", 
        "Forged carbon", "Freshwater Pearl", "Garnet", "Green Amethyst", 
        "Green/chrome diopside", "Green onyx", "Green Tourmaline", 
        "Hampton blue topaz", "Hematine", "Imperial Topaz", "Indian ruby", "Iolite", 
        "Jade", "Jasper", "Labradorite", "Lapis lazuli", "Lemon citrine", 
        "Lab-Grown Alexandrite", "Lab-Grown Amethyst", "Lab-Grown Diamond", 
        "Lab-Grown Emerald", "Lab-Grown Iolite", "Lab-Grown Ruby", 
        "Lab-Grown Sapphire", "Lab-Grown Tourmaline", "Madeira Citrine", "Malachite", 
        "Meteorite", "Milky Aquamarine", "Moonstone", "Morganite", "Mother of Pearl", 
        "Nephrite jade", "No Stone", "Olive quartz", "Opal", "orange sapphires", 
        "OTHER", "Pearl", "Peridot", "Pietersite", "Pink Amethyst", "Pink Diamond", 
        "Pink opal", "Pink Sapphire", "Pink tourmaline", "Pinolith", "Prasiolite", 
        "Pyrite", "Quartz", "Rainbow moonstone", "Red tiger's eye", 
        "Rhodolite garnet", "Rhodonite", "Riverstone", "Rubellite", "Ruby", 
        "Rutilated quartz", "Sapphire", "Smoky Quartz", "Smoky Topaz", 
        "South Sea Pearl", "Swarovski", "Tahitian Pearl", "Tantalum", "Tanzanite", 
        "Tiger Eye", "Tiger iron", "Topaz", "Tourmaline", "Tourmilated quartz", 
        "Tsavorite", "Turquoise", "Tyrone turquoise", "White Agate", 
        "White South Sea Pearl", "White Topaz", "Yellow Diamond", "Yellow Sapphires", 
        "Zircon", "Apatite", "Beryl", "Black Obsidian", "Bloodstone", "Chalcedony", 
        "Demantoid", "Hematite", "Hessonite", "Kunzite", "Kyanite", "Marcasite", 
        "Onyx", "Phrenite", "Rhodocrosite", "Selenite", "Sodalite", "Spessartite", 
        "Spinel", "Almandine Garnet", "Agate Chalcedony", "CZ Cubic Zirconia", 
        "Resin (Plastic)", "Akoya Cult Pearl", "Amber", "Bloodstone Chalcedony", 
        "Black Onyx Chalcedony", "Boulder Opal", "Chrysocolla Chalcedony", 
        "Chrysoprase Chalcedony", "Carnelian Chalcedony", "Chrome Tourmaline", 
        "Chrome Diopside", "Conch Pearl", "Cult Pearl", "Demantoid Garnet", 
        "Dendritic Agate Chal", "Dravite Tourmaline", "Fire Opal", "FW Cult Pearl", 
        "Hessonite Garnet", "Indicolite Tourmaline", "Jasper Chalcedony", 
        "Keshi Pearl", "Mabe Cultured Pearl", "Malaia Garnet", "Milky Chalcedony", 
        "Moissonite", "Natural Pearl", "Onyx Chalcedony", "Paraiba Tourmaline", 
        "Pyrope Garnet", "Prehnite", "Rock Crystal Quartz", "Rose Quartz", 
        "Rutilated Quartz", "Seed Pearl", "Spessartine Garnet", "SS Cult Pearl", 
        "Tourmalinated Quartz", "Tsavorite Garnet", "Tahitian SS Cult Pearl", 
        "Watermelon Tourmaline", "Enamel", "Prasiolite Quartz", "Glass", 
        "Other Gemstones", "Padparascha Sapphire", "Mandarin Garnet", 
        "Tigers Eye Quartz", "Lotus Garnet", "Drusy Quartz", "Chrysoberyl", 
        "Lacquer", "Multiple Gemstones", "Jelly Opal", "Black Opal", "Ebony (Wood)"
    },
    "center_stone_shape": {
        "Asscher", "Cushion", "Emerald", "Heart shape", "Kite", "Marquise", "Oval", 
        "Pear shape", "Radiant", "Round", "Square", "Trillion", "Unusual", "Princess", 
        "Rose-Cut", "Bullet", "Moval", "Trapezoid", "Ashoka", "Bead", "Baguette", 
        "Briolette", "Cabochon", "Checkerboard", "Hexagon", "Half Moon", "Crisscut", 
        "Cushion Cabochon", "Crisscut Baguette", "Crisscut Emerald", 
        "Crisscut Tapered Baguette", "Crisscut Lamour Classic", "Crisscut Lamour Pear", 
        "Crisscut Lamour Cushion", "Crisscut Lamour Oval", "Crisscut Round", 
        "Cushion Checkerboard", "Epaulet", "French Cut Baguette", "Geode", 
        "Heart Cabochon", "Half Moon Step Cut", "Multiple Shapes", "Marquise Cabochon", 
        "Oval Cabochon", "Old European", "Old Mine", "Oval Checkerboard", 
        "Oval Rose Cut", "Pear Shape Cabochon", "Pear Shape Checkerboard", 
        "Pear Shape Rose Cut", "Rose Cut", "Round Cabochon", "Round Checkerboard", 
        "Rough", "Rondelle", "Shield", "Slice/Slab", "Square Checkerboard", 
        "Square Step Cut", "Trillion Cabochon", "Trillion Checkerboard"
    },
    "side_stone_1_type": {"Diamond"},
    "side_stone_1_shape": {
        "Asscher", "Cushion", "Emerald", "Heart shape", "Kite", "Marquise", "Oval", 
        "Pear shape", "Radiant", "Round", "Square", "Trillion", "Unusual", "Princess", 
        "Rose-Cut", "Bullet", "Moval", "Trapezoid", "Ashoka", "Bead", "Baguette", 
        "Briolette", "Cabochon", "Checkerboard", "Hexagon", "Half Moon", "Crisscut", 
        "Cushion Cabochon", "Crisscut Baguette", "Crisscut Emerald", 
        "Crisscut Tapered Baguette", "Crisscut Lamour Classic", "Crisscut Lamour Pear", 
        "Crisscut Lamour Cushion", "Crisscut Lamour Oval", "Crisscut Round", 
        "Cushion Checkerboard", "Epaulet", "French Cut Baguette", "Geode", 
        "Heart Cabochon", "Half Moon Step Cut", "Multiple Shapes", "Marquise Cabochon", 
        "Oval Cabochon", "Old European", "Old Mine", "Oval Checkerboard", 
        "Oval Rose Cut", "Pear Shape Cabochon", "Pear Shape Checkerboard", 
        "Pear Shape Rose Cut", "Rose Cut", "Round Cabochon", "Round Checkerboard", 
        "Rough", "Rondelle", "Shield", "Slice/Slab", "Square Checkerboard", 
        "Square Step Cut", "Trillion Cabochon", "Trillion Checkerboard", 
        "Straight baguette", "Tapered baguette"
    },
    "side_stone_2_type": {
        "Abalone", "Agate", "Akoya Pearl", "Alexandrite", "Amazonite", "Amethyst", 
        "Aquamarine", "Black Diamond", "Black Freshwater Pearl", "Black mother of pearl", 
        "Black Onyx", "Black orchid", "Black spinel", "Black South Sea Pearl", 
        "Blue Chalcedony", "Blue Diamond", "Blue Sapphire", "Blue Topaz", 
        "Brown Diamond", "Carnelian", "Champagne Diamond", "Charoite", 
        "Chinese turquoise", "CHRYSOCOLLA", "Chrysoprase", "Citrine", 
        "Color Change Garnet", "Coral", "Corundum", "Crystal", 
        "Cultured freshwater pearls", "Cultured Pearl", "CZ", "Diamond", "Emerald", 
        "Freshwater Pearl", "Garnet", "Green Amethyst", "Green/chrome diopside", 
        "Green onyx", "Green Tourmaline", "Hematine", "Imperial Topaz", "Iolite", 
        "Jade", "Jasper", "Labradorite", "Lapis lazuli", "Lab-Grown Alexandrite", 
        "Lab-Grown Amethyst", "Lab-Grown Diamond", "Lab-Grown Emerald", 
        "Lab-Grown Iolite", "Lab-Grown Ruby", "Lab-Grown Sapphire", 
        "Lab-Grown Tourmaline", "Malachite", "Moonstone", "Morganite", 
        "Mother of Pearl", "Nephrite jade", "No Stone", "Opal", "OTHER", "Pearl", 
        "Peridot", "Pink Amethyst", "Pink Diamond", "Pink opal", "Pink Sapphire", 
        "Pink tourmaline", "Prasiolite", "Pyrite", "Quartz", "Rainbow moonstone", 
        "Rhodolite garnet", "Rhodonite", "Rubellite", "Ruby", "Rutilated quartz", 
        "Sapphire", "Smoky Quartz", "Smoky Topaz", "South Sea Pearl", "Swarovski", 
        "Tahitian Pearl", "Tantalum", "Tanzanite", "Tiger Eye", "Topaz", "Tourmaline", 
        "Tourmilated quartz", "Tsavorite", "Turquoise", "White Agate", 
        "White South Sea Pearl", "White Topaz", "Yellow Diamond", "Zircon", 
        "Apatite", "Beryl", "Black Obsidian", "Bloodstone", "Chalcedony", 
        "Demantoid", "Hematite", "Hessonite", "Kunzite", "Kyanite", "Marcasite", 
        "Onyx", "Phrenite", "Rhodocrosite", "Selenite", "Sodalite", "Spessartite", 
        "Spinel", "Almandine Garnet", "Agate Chalcedony", "CZ Cubic Zirconia", 
        "Resin (Plastic)", "Akoya Cult Pearl", "Amber", "Bloodstone Chalcedony", 
        "Black Onyx Chalcedony", "Boulder Opal", "Chrysocolla Chalcedony", 
        "Chrysoprase Chalcedony", "Carnelian Chalcedony", "Chrome Tourmaline", 
        "Chrome Diopside", "Conch Pearl", "Cult Pearl", "Demantoid Garnet", 
        "Dendritic Agate Chal", "Dravite Tourmaline", "Fire Opal", "FW Cult Pearl", 
        "Hessonite Garnet", "Indicolite Tourmaline", "Jasper Chalcedony", 
        "Keshi Pearl", "Mabe Cultured Pearl", "Malaia Garnet", "Milky Chalcedony", 
        "Moissonite", "Natural Pearl", "Onyx Chalcedony", "Paraiba Tourmaline", 
        "Pyrope Garnet", "Prehnite", "Rock Crystal Quartz", "Rose Quartz", 
        "Rutilated Quartz", "Seed Pearl", "Spessartine Garnet", "SS Cult Pearl", 
        "Tourmalinated Quartz", "Tsavorite Garnet", "Tahitian SS Cult Pearl", 
        "Watermelon Tourmaline", "Enamel", "Prasiolite Quartz", "Glass", 
        "Other Gemstones", "Padparascha Sapphire", "Mandarin Garnet", 
        "Tigers Eye Quartz", "Lotus Garnet", "Drusy Quartz", "Chrysoberyl", 
        "Lacquer", "Multiple Gemstones", "Jelly Opal", "Black Opal", "Ebony (Wood)"
    },
    "side_stone_2_shape": {
        "Asscher", "Cushion", "Emerald", "Heart shape", "Kite", "Marquise", "Oval", 
        "Pear shape", "Radiant", "Round", "Square", "Trillion", "Unusual", "Princess", 
        "Rose-Cut", "Bullet", "Moval", "Trapezoid", "Ashoka", "Bead", "Baguette", 
        "Briolette", "Cabochon", "Checkerboard", "Hexagon", "Half Moon", "Crisscut", 
        "Cushion Cabochon", "Crisscut Baguette", "Crisscut Emerald", 
        "Crisscut Tapered Baguette", "Crisscut Lamour Classic", "Crisscut Lamour Pear", 
        "Crisscut Lamour Cushion", "Crisscut Lamour Oval", "Crisscut Round", 
        "Cushion Checkerboard", "Epaulet", "French Cut Baguette", "Geode", 
        "Heart Cabochon", "Half Moon Step Cut", "Multiple Shapes", "Marquise Cabochon", 
        "Oval Cabochon", "Old European", "Old Mine", "Oval Checkerboard", 
        "Oval Rose Cut", "Pear Shape Cabochon", "Pear Shape Checkerboard", 
        "Pear Shape Rose Cut", "Rose Cut", "Round Cabochon", "Round Checkerboard", 
        "Rough", "Rondelle", "Shield", "Slice/Slab", "Square Checkerboard", 
        "Square Step Cut", "Trillion Cabochon", "Trillion Checkerboard", 
        "Straight baguette", "Tapered baguette"
    },
    "engagement_set_type": {"Engagement Ring", "Wedding Set"},
    "engagement_ring_type": {
        "Halo", "Side Stone", "Solitaire", "Three Stone", "Two Stone", "Eternity", 
        "Invisible", "Flush", "Jacket/Wrap", "bead set"
    },
    "wedding_band_type": {
        "Antique", "Classic", "Contemporary", "Modern", "Plain", "Vintage", 
        "Eternity", "Bar", "Solitaire", "Three Stone", "U-Prong", "Jacket/Wrap"
    },
    "wedding_band_setting_type": {
        "Channel", "Pave", "Prong", "Bezel", "Shared-Prong", "Tension", "Invisible", 
        "Flush", "Jacket/Wrap", "bead set", "Bar", "Solitaire", "Three Stone", "U-Prong"
    },
    "wedding_band_stone_continuity": {
        "Eternity", "Half Way", "Separated", "Three Quarter", "Religious"
    },
    "fashion_ring_type": {
        "Cocktail Ring", "Halo", "Religious", "Sidestone", "Cord", "Two Stone", 
        "Band", "Bypass", "Cluster", "Eternity Band", "Hug", "Link", "Mult Finger", 
        "Signet", "Stack", "Stretch"
    },
    "earring_type": {
        "Halo", "Stud", "Hoops", "dangle", "Huggies", "Threader", "Cluster", 
        "Jacket", "Drops", "chandelier"
    },
    "necklace_type": {
        "Bead", "Chain", "Choker", "Collar", "Pendant", "Statement", "Solitaire", 
        "Locket", "Strand", "Lariat (Y)", "Link", "Charm"
    },
    "bracelet_type": {
        "Bangle", "Bead", "Chain", "Charms", "Cable", "Link", "Leather", "Tennis", 
        "Cuff", "Station", "Stretch"
    },
    "accessory_type": {
        "Backpack", "Bag", "Belt", "Belt Buckle", "Brooch", "Card Holder", "Cufflink", 
        "Key Rings", "Money Clips", "Pen Pouch", "Pocket Knife", "Strap", "Tie Bar", 
        "Wallet", "Jewelry Case", "Jewelry Box", "Flask", "Flowers", "Keychain", 
        "Lapel Pin", "Moneyclip", "Tie Accessory", "BR/CH (Bracelet and Charm)", 
        "Keyring", "Business Card Holder", "Clutch", "Coin Purse", "Compact", 
        "Fullbead Handbag", "Handbag", "Luggage Tag", "Lipstick Holder", "Mirror", 
        "Pillbox", "Ballpoint Pen", "Fineliner Pen", "Fountain Pen", "Pencil", 
        "Rollerball", "Set", "Cufflinks/Shirt Studs"
    },
    "theme": {
        "Animal", "Flower", "Love", "Nature", "Religious", "Sea Life", "Space", 
        "Round", "Sports", "Sun", "Wedding", "Star", "Tree", "Ocean", "Kids", "Machine", "Rock"
    },
    "occasion": {
        "Anniversary", "Baby Birth", "Birthday", "Engagement", "Graduation", 
        "Mothers Day", "Nature", "Sports", "Thanksgiving", "Valentine's Day"
    },
    "jewelry_shape": {
        "Animal", "Bird", "Cross", "Fish", "Flower", "Heart", "Pentagon", "Star", 
        "Tree", "Triangle", "Hexagon", "Octagon", "Angel", "Ball", "Bee", "Bicycle", 
        "Bow", "Buddha", "Butterfly", "Chai", "Chevron (V)", "Circle", "Clover", 
        "Coil", "Compass", "Crab", "Crescent Moon & Star", "Crown", "Crescent Moon", 
        "Curved Bar", "Cushion", "Disc", "Dome", "Dog Tag", "Drop (Pear Shaped)", 
        "Egg", "Evil Eye", "Fleur de Lis", "Feather", "Frog", "Geometric", "Hamsa", 
        "Horseshoe", "Infinity", "Initial", "Key", "Kite", "Knot", "Ladybug", "Leaf", 
        "Lotus", "Lightening/Thunder Bolt", "Boot", "Navette (Marquise Shaped)", 
        "Number", "Oval", "Padlock", "Peace Sign", "Pineapple", "Rainbow", 
        "Rectangle", "Sunburst", "Script", "Scroll", "Safety Pin", "Shamrock", 
        "Shield", "Skull", "Snake", "Snowflake", "Square", "Star of David", "Swirl", 
        "Tassel", "Triangular", "Twist", "Wave", "Wishbone", "Yin Yang", "Zodiac", "Zig Zag"
    },
    "motif": {
        "Army", "Hawaii", "Kids", "Love", "Ocean", "Sea Life", "Space", "Sports", "Island"
    },
    "finishing_type": {
        "Angle Satin", "Angle Stone", "Bead", "Cross Satin", "Disk 3", "Distress", 
        "Hammered", "Religiouse", "Rock", "Satin", "Stone", "Treebark 1", "Treebark 3", 
        "Brushed", "Engraving", "Milgrain", "Combination", "Damascus", 
        "Filigree Engraved", "Florentine", "High Polish", "Oxidized", "Sandblasted"
    },
    "estate_period": {
        "Art Deco (1920-1939)", "Art Nouveau (1890-1914)", "Edwardian (1901-1915)", 
        "Georgian (1714-1837)", "Mid-Century (1940-1960)", "Retro (1940-1950)", 
        "Victorian (1837-1901)"
    },
    "holiday_code": {
        "Birthday", "Christmas", "Easter", "Halloween", "Judaica", 
        "Fourth of July/Patriotic", "St. Patrick's Day", "Wedding Day"
    },
    "chain_type": {
        "Rope", "Box", "Snake", "Cable", "Oval", "Paper Clip", "Figaro", "Mariner", 
        "Franco", "Miami Cuban", "Curb", "Singapore", "Wheat", "Rolo", "Serpentine", 
        "Ball", "Cobra", "Cuban", "Byzantine", "Herringbone", "Bead", "Anchor", 
        "Omega", "Bismark", "Rosary", "Valentino", "Extension"
    },
    "clasp_type": {
        "Omega", "Lobster", "Screw", "Toggle", "Bolo", "Magnetic", "Spring", 
        "Barrel", "Box", "Safety", "Endless", "Plunger", "Latch", "Hidden", 
        "French Hook", "Slide", "Kidney Wire", "Foldover", "Hook", "Push", "Snap", 
        "Springring", "Eagle", "Diamond", "Pearl"
    },
    "earring_back": {
        "Omega", "Screwback", "Clip", "Leverback", "Post", "La Pousette", 
        "Threader", "Safety", "Friction", "Locking", "Wire", "Push", "Jumbo"
    }
}

# --- NEW WATCH SCHEMA OPTIONS ---
VALID_BC365_WATCH_OPTIONS: Dict[str, set] = {
    "functions_complications": {
        "Date", "Day", "Centre Hour", "Instantaneous Date", "Minute and Second Hand", 
        "Stop-seconds for precise time setting", "Power Reserve", "Month", "Moon Phase", 
        "Second Hand", "Chronograph", "Chronometer", "minute repeater", 
        "perpetual calendar", "alarm", "split chronometer", "annual calendar", 
        "tourbillon", "GMT", "World Time"
    },
    "watch_style": {"Casual", "Dress", "Fashion", "Luxury", "Sport", "Diver", "Pocket"},
    "movement_type": {
        "Automatic", "Hand", "Quartz", "Manual", "Spring Drive", "Self Winding", 
        "Solar", "Eco-Drive", "Mechanical/Manual", "Automatic AND Manual", "Automatic/Self Winding"
    },
    "display_type": {"Analog", "Analog/Digital", "Digital", "LED", "1 Subdial", "2 Subdial", "3 Subdial"},
    "case_shape": {"Heart", "Oval", "Rectangular", "Round", "Square", "Tonneau", "Triangular", "Cushion", "Other"},
    "dial_color": {
        "Beige", "Black", "Blue", "Blue/Black", "Blue/Red", "Brown", "Burgundy", 
        "Champagne", "Chocolate/Black", "Gold", "Gray", "Green", "Ivory", "Maroon", 
        "Not Applicable", "Navy Blue", "Onyx", "Orange", "Pink", "Purple", "Red", 
        "Rose Gold", "Silver", "Turquoise", "Violet", "White", "Yellow", "Yellow Gold", 
        "Slate", "Red Grape", "Black Mother of Pearl", "BlueMother of Pearl", "Cream", 
        "Golden", "Grey Mother of Pearl", "Multi Color", "Pink Mother of Pearl", 
        "Skeleton", "White Mother of Pearl", "Diamond", "Reverso"
    },
    "case_back": {"Closed", "Open", "Skeleton"},
    "dial_motif": {
        "Celebration", "Eisenkiesel", "Floral", "Fluted", "Meteorite", "Mother Of Pearl", 
        "Palm", "Pave Diamonds and Sapphires", "Pave Diamonds", "No Motf/Plain Color"
    },
    "watch_display_number_type": {
        "A/Dot", "Arabic and Index", "Arabic and Roman", "Arabic", "Colored Stone/Crystal", 
        "Diamond", "Diamond and Arabic", "Diamond and Dot", "Diamond and Index", 
        "Diamond and Roman", "Digital", "Dot", "Dot and Index", "Index and Colored Stone/Crystal", 
        "Index and Roman", "Index", "Roman and Colored Stone/Crystal", "Roman", "Dot and Roman"
    },
    "dial_embellishment": {"Crystal", "Diamonds", "Gemstone", "Glitter", "Pearl", "Rhinestone", "Stud"},
    "case_material": {
        "Gold 14K", "Gold 18K", "Platinum", "Silver", "Stainless Steel", "Rolesor 18 Carat", 
        "Rolesium Platinum", "Titanium", "PVD", "Bronze", "Breitlight", "Ceramic", 
        "Carbon Fiber", "Diamond Like Carbon", "Platinum and Stainless Steel", 
        "Polymer/Plastic", "Rose Gold", "Rose Gold and Platinum", "Rose Gold and Stainless Steel", 
        "Rose Tone", "Rose Tone and Stainless Steel", "Stainless Steel and Blue Tone", 
        "Stainless Steel and Black PVD", "Stainless Steel and Brass", "Stainess Steel and Bronze", 
        "Stainless Steeel and Black Tone", "Stainless Steel and Ceramic", 
        "Stainless Steel and Carbon Fiber", "Stainless Steel and Titanium Coating", 
        "Tungsten Carbide", "Tantalum", "White Gold Rhodium Plated", 
        "White Gold Rhodium Plated and Platinum", "White Gold Rhodium Plated and Stainless Steel", 
        "Yellow Gold", "Yellow Gold and Platinum", "Yellow Gold and Stainless Steel", 
        "Yellow Tone", "Yellow Tone and Stainless Steel", "Ceratanium"
    },
    "strap_bracelet_type": {
        "Bangle", "Bracelet", "Bracelet and Strap", "Cuff", "Strap", "Bracelet and 2 Straps", 
        "Strap Set of 2", "Strap Set of 3", "Strap Set of 5"
    },
    "strap_bracelet_material": {
        "Gold 14K", "Gold 18K", "Alligator Leather", "Platinum", "Leather", "Silver", 
        "Stainless Steel", "Rolesor 18 Carat", "Rolesium Platinum", "Titanium", "Calfskin", 
        "Sharkskin", "Ostrich", "Crocodile", "Elastomer", "Silicone", "Rubber", "Nylon", 
        "Cloth", "Canvas", "Lizard", "Pig", "Kevlar", "Cordura", "Carbon Fiber", "Lamb Skin", 
        "Ceramic", "Appleskin", "Fabric", "Fabric and Leather", "Grosgrain", 
        "Leather and Nylon Set of 2", "Grain", "Microfiber", "PVD", "Satin", "Snakeskin", 
        "Textile", "Vegan Leather", "Oysterflex", "cord", "Bronze", "Diamond Like Carbon", 
        "Polymer/Plastic", "Rose Gold", "Rose Gold and Platinum", "Rose Gold and Stainless Steel", 
        "Rose Tone", "Rose Tone and Ceramic", "Rose Tone and Stainless Steel", 
        "Sterling Silver Plated Product", "Stainess Steel and Blue Tone", "Stainless Steel and Black PVD", 
        "Stainless Steel and Brass", "Stainess Steel and Bronze", "Stainless Steel and Black Tone", 
        "Stainless Steel and Ceramic", "Stainless Steel and Carbon Fiber", 
        "Stainless Steel and Titanium Coating", "Tungsten Carbide", "Titanium", "Tantalum", 
        "White Gold Rhodium Plated", "White Gold Rhodium Plated and Platinum", 
        "White Gold Rhodium Plated and Stainless Steel", "Yellow Gold", "Yellow Gold and Platinum", 
        "Yellow Gold and Stainless Steel", "Yellow Tone", "Yellow Tone and Stainless Steel"
    },
    "case_color": {
        "Black", "Brown", "Red", "Rose", "White", "Yellow", "Yellow-White", "Blue", 
        "Golden", "Gray", "Green", "Multi Colored", "Orange", "Pink", "Purple", "Rose-White"
    },
    "strap_color": {
        "Black", "Brown", "Blue", "Red", "Rose", "White", "Yellow", "Golden", "Gray", 
        "Green", "Multi Colored", "Orange", "Pink", "Purple"
    },
    "strap_secondary_color": {
        "Black", "Blue", "Brown", "Cream", "Golden", "Gray", "Green", "Orange", "Pink", "Purple"
    },
    "crystal_material": {"Glass", "Plastic", "Sapphire", "Synthetics Sapphire"},
    "special_functions": {
        "Activity tracker", "Alarm", "Altimeter", "Back light", "Barometer", "Calculator", 
        "Calendar", "Calories counter", "Camera", "Chronograph", "Compass", "Countdown", 
        "Distance tracking", "Email", "GPS", "Heart rate monitor", "Lap timer", "Messages", 
        "Multi time zone", "Music player", "Night light", "Pedometer", "Phone", "Pulse monitor", 
        "Sleep monitor", "Social media", "Solar powered", "Stop watch", "Voice control", "Web search"
    },
    "clasp_type": {
        "Butterfly Deployant", "Hidden Folding (Crown)", "Non-Closure", "Pin Buckle", 
        "Sliding Buckle", "Velcro Strap"
    },
    "bezel_type": {
        "Compass", "Countdown", "Count Up", "Diamond", "Fluted", "GMT", "Pattern", "Plain", 
        "Rolex Ring Command", "Slide rule", "Tachymeter", "Ceramic", "Numbered"
    },
    "winding_crown": {"Domed", "Triplock", "Twinlock"},
    "gender": {"Baby", "Gents", "Ladies", "Unisex"},
    "limited_production": {"Yes", "No"},
    "watch_size": {"L", "M", "S", "XL", "XS", "mini"}
}

def _normalize_to_bc365(field: str, raw_value: Any, category: str = "jewelry") -> Optional[str]:
    """
    Forces a raw extracted string to match the EXACT valid BC365 Master Data option.
    Uses case-insensitive exact matching, then longest-substring fallback for synonyms.
    """
    if not raw_value or not isinstance(raw_value, str):
        return None
        
    valid_options = set()
    if category == "watch":
        valid_options = VALID_BC365_WATCH_OPTIONS.get(field, set())
    else:
        valid_options = VALID_BC365_OPTIONS.get(field, set())
        
    if not valid_options:
        # For text/numeric fields not in the strict sets (e.g. case_diameter, calibre)
        return raw_value.strip()
        
    raw_clean = raw_value.strip()
    raw_lower = raw_clean.lower()
    
    # 1. Exact match (case-insensitive)
    for opt in valid_options:
        if opt.lower() == raw_lower:
            return opt
            
    # 2. Substring match
    best_match = None
    for opt in valid_options:
        opt_lower = opt.lower()
        if opt_lower in raw_lower or raw_lower in opt_lower:
            if best_match is None or len(opt) > len(best_match):
                best_match = opt
                
    return best_match

def _build_attributes_from_text_and_vision(
    brand: str,
    text: str,
    vision_results: List[Dict[str, Any]],
    item_number: str,
    pre_filled_attrs: Optional[Dict[str, Any]] = None,
    category: str = "jewelry"
) -> Dict[str, Any]:
    
    if category == "watch":
        return _build_watch_attributes_from_text_and_vision(
            brand, text, vision_results, item_number, pre_filled_attrs
        )

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

    # STEP 0: PRE-FILL FROM INVOICE
    if pre_filled_attrs and isinstance(pre_filled_attrs, dict):
        for key, value in pre_filled_attrs.items():
            if key in attrs and value is not None:
                attrs[key] = _normalize_to_bc365(key, str(value), category)

    # 2. Parse JSON returned by the Vision AI
    for v_res in vision_results:
        analysis_text = v_res.get("analysis", "")
        if not analysis_text:
            continue
        vision_attrs = _extract_json_from_text(analysis_text)
        if vision_attrs and isinstance(vision_attrs, dict):
            for key, value in vision_attrs.items():
                if key in attrs and attrs[key] is None and value is not None:
                    attrs[key] = _normalize_to_bc365(key, str(value), category)

    # -----------------------------------------------------------------------
    # 3. PRE-PROCESS: Normalize European Karats & Multilingual Terms
    # -----------------------------------------------------------------------
    if "750/1000" in text_lower or "750â/1000" in text_lower:
        text_lower = text_lower.replace("750/1000", "18k").replace("750â/1000", "18k")
    if "585/1000" in text_lower:
        text_lower = text_lower.replace("585/1000", "14k")
    if "or rose" in text_lower or "oro rosa" in text_lower:
        text_lower = text_lower.replace("or rose", "18k rose gold").replace("oro rosa", "18k rose gold")
    if "or blanc" in text_lower or "oro bianco" in text_lower:
        text_lower = text_lower.replace("or blanc", "18k white gold").replace("oro bianco", "18k white gold")
    if "or jaune" in text_lower or "oro giallo" in text_lower:
        text_lower = text_lower.replace("or jaune", "18k yellow gold").replace("oro giallo", "18k yellow gold")
    if "platine" in text_lower or "platino" in text_lower:
        text_lower = text_lower.replace("platine", "platinum").replace("platino", "platinum")
    if "diamant" in text_lower or "diamante" in text_lower:
        text_lower = text_lower.replace("diamant", "diamond").replace("diamante", "diamond")
    if "taille brillant" in text_lower or "brilliant-cut" in text_lower:
        text_lower = text_lower.replace("taille brillant", "round").replace("brilliant-cut", "round")
    if "taille baguette" in text_lower:
        text_lower = text_lower.replace("taille baguette", "baguette")

    # 4. STONE EXTRACTION
    if attrs.get("center_stone_type") is None:
        mentioned_stones = []
        for stone in VALID_BC365_OPTIONS.get("center_stone_type", set()):
            if stone.lower() in ("other gemstones", "no stone", "enamel", "glass", "resin (plastic)"): continue
            if stone.lower() in text_lower: mentioned_stones.append(stone)

        if mentioned_stones:
            first_stone_idx = len(text_lower)
            first_stone = mentioned_stones[0]
            for s in mentioned_stones:
                idx = text_lower.find(s.lower())
                if idx != -1 and idx < first_stone_idx:
                    first_stone_idx = idx
                    first_stone = s
            if len(mentioned_stones) > 1 and "Diamond" in mentioned_stones:
                if "with diamond" in text_lower or "and diamond" in text_lower:
                    for s in mentioned_stones:
                        if s != "Diamond": attrs["center_stone_type"] = _normalize_to_bc365("center_stone_type", s, category); break
                else: attrs["center_stone_type"] = _normalize_to_bc365("center_stone_type", first_stone, category)
            else: attrs["center_stone_type"] = _normalize_to_bc365("center_stone_type", first_stone, category)

    if attrs.get("side_stone_1_type") is None:
        if ("paved" in text_lower or "pave" in text_lower or "halo" in text_lower) and attrs.get("center_stone_type") == "Diamond":
            attrs["side_stone_1_type"] = "Diamond"
        else:
            for stone in VALID_BC365_OPTIONS.get("center_stone_type", set()):
                if stone.lower() in ("other gemstones", "no stone", "enamel", "glass", "resin (plastic)"): continue
                if stone.lower() in text_lower and stone != attrs.get("center_stone_type"):
                    attrs["side_stone_1_type"] = _normalize_to_bc365("side_stone_1_type", stone, category); break

    # 5. COLOR & SHAPE EXTRACTION
    if attrs.get("stone_primary_color") is None and "diamond" in text_lower:
        attrs["stone_primary_color"] = _normalize_to_bc365("stone_primary_color", "White", category)
    if attrs.get("center_stone_shape") is None and "round" in text_lower:
        attrs["center_stone_shape"] = _normalize_to_bc365("center_stone_shape", "Round", category)

    # 6. MATERIAL & CATEGORY OVERRIDES
    if attrs.get("metal_type") is None:
        if "platinum" in text_lower or "950" in text_lower:
            attrs["metal_type"] = "950PL"
            if attrs.get("metal_color") is None: attrs["metal_color"] = "White"
        elif "sterling" in text_lower or "925" in text_lower or "silver" in text_lower:
            attrs["metal_type"] = "STSILVER"
            if attrs.get("metal_color") is None: attrs["metal_color"] = "White"
        elif "stainless steel" in text_lower or "steel" in text_lower:
            attrs["metal_type"] = "STSTEEL"
            if attrs.get("metal_color") is None: attrs["metal_color"] = "GREY"
        elif "18k rose" in text_lower or "18kt rose" in text_lower:
            attrs["metal_type"] = "18K"
            if attrs.get("metal_color") is None: attrs["metal_color"] = "Rose"
        elif "18k white" in text_lower or "18kt white" in text_lower:
            attrs["metal_type"] = "18K"
            if attrs.get("metal_color") is None: attrs["metal_color"] = "White"
        elif "18k yellow" in text_lower or "18kt yellow" in text_lower or "18k" in text_lower:
            attrs["metal_type"] = "18K"
            if attrs.get("metal_color") is None: attrs["metal_color"] = "Yellow"
        elif "14k rose" in text_lower or "14kt rose" in text_lower:
            attrs["metal_type"] = "14K"
            if attrs.get("metal_color") is None: attrs["metal_color"] = "Rose"
        elif "14k white" in text_lower or "14kt white" in text_lower:
            attrs["metal_type"] = "14K"
            if attrs.get("metal_color") is None: attrs["metal_color"] = "White"
        elif "14k yellow" in text_lower or "14kt yellow" in text_lower or "14k" in text_lower:
            attrs["metal_type"] = "14K"
            if attrs.get("metal_color") is None: attrs["metal_color"] = "Yellow"

    if attrs.get("product_type") is None:
        if "solitaire" in text_lower and "diamond" in text_lower: attrs["product_type"] = _normalize_to_bc365("product_type", "Engagement Rings", category)
        elif "engagement" in text_lower: attrs["product_type"] = _normalize_to_bc365("product_type", "Engagement Rings", category)
        elif "earring" in text_lower: attrs["product_type"] = _normalize_to_bc365("product_type", "Earrings", category)
        elif "necklace" in text_lower or "pendant" in text_lower: attrs["product_type"] = _normalize_to_bc365("product_type", "Necklaces", category)
        elif "bracelet" in text_lower or "bangle" in text_lower: attrs["product_type"] = _normalize_to_bc365("product_type", "Bracelets", category)
        elif "wedding band" in text_lower: attrs["product_type"] = _normalize_to_bc365("product_type", "Wedding Bands", category)
        elif "ring" in text_lower: attrs["product_type"] = _normalize_to_bc365("product_type", "Fashion Rings", category)

    if attrs.get("engagement_ring_type") is None and "solitaire" in text_lower:
        attrs["engagement_ring_type"] = _normalize_to_bc365("engagement_ring_type", "Solitaire", category)
        
    if attrs.get("wedding_band_setting_type") is None and ("pavé" in text_lower or "pave" in text_lower or "paved" in text_lower):
        attrs["wedding_band_setting_type"] = _normalize_to_bc365("wedding_band_setting_type", "Pave", category)

    return attrs


def _build_watch_attributes_from_text_and_vision(
    brand: str,
    text: str,
    vision_results: List[Dict[str, Any]],
    item_number: str,
    pre_filled_attrs: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    
    text_lower = (text or "").lower()
    
    # 1. Initialize all 40+ watch fields as null
    attrs = {
        "functions_complications": None, "watch_style": None, "movement_type": None,
        "display_type": None, "case_diameter": None, "case_thickness_mm": None,
        "case_shape": None, "dial_color": None, "case_back": None, "dial_motif": None,
        "watch_display_number_type": None, "dial_embellishment": None, "case_material": None,
        "strap_bracelet_type": None, "strap_bracelet_material": None, "case_color": None,
        "strap_color": None, "strap_secondary_color": None, "strap_bracelet_width_mm": None,
        "crystal_material": None, "special_functions": None, "power_reserve_hour": None,
        "water_resistance_m": None, "clasp_type": None, "watch_brand": None,
        "watch_collection": None, "bezel_type": None, "winding_crown": None,
        "calibre": None, "precision": None, "certification": None, "gender": None,
        "msrp_price": None, "year_produced": None, "limited_production": None,
        "watch_size": None, "treatment": None
    }

    # STEP 0: PRE-FILL FROM INVOICE
    if pre_filled_attrs and isinstance(pre_filled_attrs, dict):
        for key, value in pre_filled_attrs.items():
            if key in attrs and value is not None:
                attrs[key] = _normalize_to_bc365(key, str(value), "watch")

    # 2. Parse JSON returned by the Vision AI
    for v_res in vision_results:
        analysis_text = v_res.get("analysis", "")
        if not analysis_text:
            continue
        vision_attrs = _extract_json_from_text(analysis_text)
        if vision_attrs and isinstance(vision_attrs, dict):
            for key, value in vision_attrs.items():
                if key in attrs and attrs[key] is None and value is not None:
                    attrs[key] = _normalize_to_bc365(key, str(value), "watch")

    # -----------------------------------------------------------------------
    # 3. EXPANDED TEXT HEURISTICS (WITH INVOICE ABBREVIATIONS)
    # -----------------------------------------------------------------------
    if attrs.get("case_material") is None:
        # Check for combinations first (e.g., "PINK GOLD & ST CASE")
        if ("pink gold" in text_lower or "rose gold" in text_lower) and ("st case" in text_lower or "steel" in text_lower):
            attrs["case_material"] = "Rose Gold and Stainless Steel"
            if attrs.get("case_color") is None: attrs["case_color"] = "Rose"
        elif ("yellow gold" in text_lower or "gold 18k" in text_lower) and ("st case" in text_lower or "steel" in text_lower):
            attrs["case_material"] = "Yellow Gold and Stainless Steel"
            if attrs.get("case_color") is None: attrs["case_color"] = "Yellow"
        # Single materials
        elif "oystersteel" in text_lower or "stainless steel" in text_lower or "st case" in text_lower or "st bct" in text_lower:
            attrs["case_material"] = "Stainless Steel"
            if attrs.get("case_color") is None: attrs["case_color"] = "Silver"
        elif "titanium" in text_lower:
            attrs["case_material"] = "Titanium"
            if attrs.get("case_color") is None: attrs["case_color"] = "Gray"
        elif "pink gold" in text_lower or "rose gold" in text_lower:
            attrs["case_material"] = "Rose Gold"
            if attrs.get("case_color") is None: attrs["case_color"] = "Rose"
        elif "yellow gold" in text_lower or "18k gold" in text_lower:
            attrs["case_material"] = "Gold 18K"
            if attrs.get("case_color") is None: attrs["case_color"] = "Yellow"

    # FIX: Unnested case_color so it applies even if Vision AI found the material
    if attrs.get("case_color") is None:
        if attrs.get("case_material") == "Stainless Steel" or "steel" in text_lower: attrs["case_color"] = "Silver"
        elif attrs.get("case_material") == "Titanium": attrs["case_color"] = "Gray"
        elif attrs.get("case_material") == "Gold 18K": attrs["case_color"] = "Yellow"
        elif attrs.get("case_material") == "Rose Gold": attrs["case_color"] = "Rose"

    # Extract case diameter using regex
    if attrs.get("case_diameter") is None:
        dia_match = re.search(r'(\d{2,3})\s*mm\b', text_lower)
        if dia_match:
            attrs["case_diameter"] = dia_match.group(1)

    if attrs.get("dial_color") is None:
        if "black dial" in text_lower or "black background" in text_lower: attrs["dial_color"] = "Black"
        elif "blue dial" in text_lower: attrs["dial_color"] = "Blue"
        elif "white dial" in text_lower: attrs["dial_color"] = "White"
        elif "green dial" in text_lower: attrs["dial_color"] = "Green"
        elif "champagne dial" in text_lower: attrs["dial_color"] = "Champagne"
        elif "silver dial" in text_lower: attrs["dial_color"] = "Silver"

    if attrs.get("bezel_type") is None:
        if "cerachrom bezel" in text_lower or "ceramic bezel" in text_lower: attrs["bezel_type"] = "Ceramic"
        elif "fluted bezel" in text_lower: attrs["bezel_type"] = "Fluted"
        elif "paved bezel" in text_lower or "pave bezel" in text_lower or "diamond bezel" in text_lower: attrs["bezel_type"] = "Diamond"
        elif "plain bezel" in text_lower: attrs["bezel_type"] = "Plain"

    if attrs.get("dial_embellishment") is None:
        if "paved" in text_lower or "pave" in text_lower or "brilliants" in text_lower:
            attrs["dial_embellishment"] = "Diamonds"

    if attrs.get("crystal_material") is None:
        if "sapphire crystal" in text_lower or "sapphire" in text_lower: attrs["crystal_material"] = "Sapphire"
        elif "mineral crystal" in text_lower or "mineral glass" in text_lower: attrs["crystal_material"] = "Glass"

    if attrs.get("strap_bracelet_type") is None:
        if "oyster bracelet" in text_lower or "oyster, " in text_lower or "oystersteel" in text_lower or "bracelet" in text_lower or "bct" in text_lower:
            attrs["strap_bracelet_type"] = "Bracelet"
        elif "leather strap" in text_lower or "alligator" in text_lower or "strap" in text_lower:
            attrs["strap_bracelet_type"] = "Strap"

    if attrs.get("strap_bracelet_material") is None:
        if attrs.get("strap_bracelet_type") == "Bracelet" and attrs.get("case_material") == "Stainless Steel":
            attrs["strap_bracelet_material"] = "Stainless Steel"
        elif "alligator" in text_lower:
            attrs["strap_bracelet_material"] = "Alligator Leather"

    if attrs.get("strap_color") is None:
        if attrs.get("strap_bracelet_material") == "Stainless Steel": attrs["strap_color"] = "Silver"
        elif "leather strap" in text_lower or "alligator" in text_lower:
            if "black" in text_lower: attrs["strap_color"] = "Black"
            elif "brown" in text_lower: attrs["strap_color"] = "Brown"

    if attrs.get("movement_type") is None:
        if "perpetual" in text_lower or "automatic" in text_lower or "self-winding" in text_lower or "auto mvt" in text_lower or "auto movement" in text_lower:
            attrs["movement_type"] = "Automatic"
        elif "quartz" in text_lower: attrs["movement_type"] = "Quartz"
        elif "manual" in text_lower or "hand-winding" in text_lower: attrs["movement_type"] = "Manual"

    if attrs.get("functions_complications") is None:
        if "date" in text_lower: attrs["functions_complications"] = "Date"
        if "chronograph" in text_lower: attrs["functions_complications"] = "Chronograph"
        if "gmt" in text_lower: attrs["functions_complications"] = "GMT"
        if "moon phase" in text_lower: attrs["functions_complications"] = "Moon Phase"

    if attrs.get("watch_brand") is None:
        attrs["watch_brand"] = brand

    if attrs.get("watch_collection") is None:
        if "submariner" in text_lower: attrs["watch_collection"] = "Submariner"
        elif "datejust" in text_lower: attrs["watch_collection"] = "Datejust"
        elif "daytona" in text_lower: attrs["watch_collection"] = "Daytona"
        elif "gmt-master" in text_lower or "gmt master" in text_lower: attrs["watch_collection"] = "GMT-Master"
        elif "sea-dweller" in text_lower or "sea dweller" in text_lower: attrs["watch_collection"] = "Sea-Dweller"
        elif "sky-dweller" in text_lower or "sky dweller" in text_lower: attrs["watch_collection"] = "Sky-Dweller"
        elif "ballon bleu" in text_lower: attrs["watch_collection"] = "Ballon Bleu de Cartier"
        elif "tank" in text_lower: attrs["watch_collection"] = "Tank"
        elif "santos" in text_lower: attrs["watch_collection"] = "Santos"
        elif "panthere" in text_lower or "panthère" in text_lower: attrs["watch_collection"] = "Panthère"

    if attrs.get("case_shape") is None:
        if "round" in text_lower: attrs["case_shape"] = "Round"
        elif "rectangular" in text_lower or "rectangle" in text_lower: attrs["case_shape"] = "Rectangular"
        elif "square" in text_lower: attrs["case_shape"] = "Square"

    if attrs.get("display_type") is None:
        if "analog" in text_lower: attrs["display_type"] = "Analog"
        elif "digital" in text_lower: attrs["display_type"] = "Digital"

    if attrs.get("case_back") is None:
        if "solid case back" in text_lower or "closed case back" in text_lower or "screw-down case back" in text_lower: 
            attrs["case_back"] = "Closed"
        elif "transparent case back" in text_lower or "open case back" in text_lower or "skeleton" in text_lower: 
            attrs["case_back"] = "Open"

    return attrs


# ---------------------------------------------------------------------------
# Workflow orchestration
# ---------------------------------------------------------------------------
def run_jewelry_workflow(payload: JewelryRequest, pre_filled_attrs: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    category = payload.category.lower()
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

    if source_url:
        resolved_url = source_url
        confidence_notes.append(f"Using provided source_url directly: {resolved_url}")
    else:
        if vendor_item_number:
            search_query = f"{brand} {vendor_item_number}"
        elif upc_code:
            search_query = f"{brand} {upc_code}"
        else:
            raise HTTPException(status_code=400, detail="Either vendor_item_number, upc_code, or source_url must be provided.")
            
    image_urls = []
    
    if not source_url:
        if vendor_item_number:
            search_query = f"{brand} {vendor_item_number}"
        elif upc_code:
            search_query = f"{brand} {upc_code}"
        else:
            raise HTTPException(status_code=400, detail="Either vendor_item_number, upc_code, or source_url must be provided.")

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
        brand_lower = brand.lower()
        item_to_use = vendor_item_number or upc_code
        if brand_lower == 'cartier' and item_to_use:
            resolved_url = f"https://www.cartier.com/en-us/jewelry/-/{item_to_use}.html"
            confidence_notes.append(f"Firecrawl search failed. Dynamically constructed Cartier URL: {resolved_url}")
        elif brand_lower == 'tiffany' and item_to_use:
            resolved_url = f"https://www.tiffany.com/jewelry/-/{item_to_use}"
            confidence_notes.append(f"Firecrawl search failed. Dynamically constructed Tiffany URL: {resolved_url}")
        elif brand_lower == 'david yurman' and item_to_use:
            resolved_url = f"https://www.davidyurman.com/-{item_to_use}.html"
            confidence_notes.append(f"Firecrawl search failed. Dynamically constructed DY URL: {resolved_url}")
        elif upc_code:
            resolved_url = f"https://www.upcitemdb.com/upc/{upc_code}"
            confidence_notes.append(f"Firecrawl search failed. Falling back to UPC database.")
        else:
            raise HTTPException(status_code=404, detail=f"Firecrawl found 0 search results for '{brand} {vendor_item_number}'. Please provide the exact 'source_url' parameter in the payload.")

    if not image_urls and resolved_url:
        try:
            confidence_notes.append(f"Search yielded no images. Attempting direct scrape of: {resolved_url}")
            scrape_result = _run_firecrawl_scrape(resolved_url)
            scrape_items = scrape_result.get("data", [])
            if scrape_items:
                if not page_text:
                    page_text = scrape_items[0].get("description", "") or ""
                image_urls = scrape_items[0].get("images", [])
                if image_urls:
                    confidence_notes.append("Direct scrape fallback successfully extracted product images.")
        except Exception as exc:
            confidence_notes.append(f"Direct scrape fallback failed: {exc}")

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
            
            # Route prompt based on category
            prompt = VISION_EXTRACTION_PROMPT
            if category == "watch":
                prompt = WATCH_VISION_EXTRACTION_PROMPT
                
            vision = _analyze_image(local_path, prompt)
            vision_results.append(vision)
            images.append(ImageEvidence(url=img_url, view_type=view_type, alt_text=f"{view_type.title()} view of {brand} {item_number or upc_code}"))
        except Exception as exc:
            error_msg = f"Image processing/analysis failed for {img_url}: {exc}"
            logger.warning(error_msg)
            confidence_notes.append(error_msg)

    combined_text = f"{page_text} {' '.join(v.get('analysis','') for v in vision_results)}"
    
    attrs_dict = _build_attributes_from_text_and_vision(
        brand, page_text, vision_results, item_number or upc_code, pre_filled_attrs, category
    )

    return {
        "item": {"brand": brand, "vendor_item_number": vendor_item_number, "upc_code": upc_code, "source_url": source_url, "resolved_item_url": resolved_url, "category": category},
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
    logger.info("Jewelry & Watch Agent API starting up on %s:%s", API_HOST, API_PORT)
    yield
    logger.info("Jewelry & Watch Agent API shutting down")

app = FastAPI(
    title="Jewelry & Watch Attribute Recognition API",
    description="Exposes jewelry & watch recognition workflow for Microsoft Business Central",
    version="1.1.0",
    lifespan=lifespan,
)

@app.get("/health")
async def health():
    return {"status": "ok", "service": SERVICE_NAME}

@app.post("/api/jewelry/recognize")
def recognize(req: JewelryRequest):
    logger.info("Received item request: category=%s, brand=%s, vendor=%s", req.category, req.brand, req.vendor_item_number)
    try:
        result = run_jewelry_workflow(req, req.pre_filled_attributes)
        return JSONResponse(content=result)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Workflow failed")
        raise HTTPException(status_code=500, detail=f"Internal error: {exc}")

# ---------------------------------------------------------------------------
# Invoice Prompt (For local LLM text extraction)
# ---------------------------------------------------------------------------
INVOICE_EXTRACTION_PROMPT = """You are an expert data entry clerk for a jewelry/watch company. Analyze this invoice text and extract the data into a JSON object.

RULES:
1. Find the Vendor Name, Invoice Number, and Invoice Date.
2. Find the line items. For EACH line item, extract:
   - vendor_item_number (the SKU or style number)
   - quantity (number)
   - price (number, float)
   - description (the exact text describing the item)
   - brand (infer from context if not explicitly stated)
   - category (either "jewelry" or "watch")
   - attributes: Based ONLY on the item description text, extract jewelry or watch attributes into a generic JSON object. If a value is not in the text, use null. Do not guess visual traits.
   
Return ONLY valid JSON matching this structure:
{
  "vendor_name": "",
  "vendor_invoice_no": "",
  "vendor_invoice_date": "",
  "items": [
    {
      "vendor_item_number": "",
      "quantity": 1.0,
      "price": 0.0,
      "description": "",
      "brand": "",
      "category": "jewelry",
      "attributes": {}
    }
  ]
}"""

from pdfminer.high_level import extract_text

def _clean_ocr_text(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r'[^aeiouyAEIOUY]+', '', text)
    text = re.sub(r'(\d)\s*([A-Za-z]+)\s+', r'\1 \2 ', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()

def _extract_text_from_pdf(file_path: str) -> str:
    try:
        from pdfminer.high_level import extract_text
        text = extract_text(file_path)
        if len(text.strip()) > 50:
            return text
    except Exception as e:
        logger.warning(f"Pdfminer text extraction failed: {e}")
    
    logger.error("PDF contains no digital text (it is a scanned image). This API does not support image-based OCR.")
    raise HTTPException(
        status_code=422, 
        detail="This PDF contains no digital text (it is a scanned image). Please process scanned PDFs through an OCR service (like Azure Document Intelligence or Tesseract) before sending to this API."
    )

def _ask_local_llm(prompt: str, text: str) -> Dict[str, Any]:
    from service.vision_client import VISION_API_URL, VISION_MODEL
    
    payload = {
        "model": VISION_MODEL,
        "prompt": f"{prompt}\n\nINVOICE TEXT:\n{text}",
        "stream": False,
        "options": {"temperature": 0.1}
    }
    
    resp = requests.post(f"{VISION_API_URL}/api/generate", json=payload, timeout=120)
    resp.raise_for_status()
    raw = resp.json().get("response", "")
    return _extract_json_from_text(raw) or {}

@app.post("/api/invoice/parse", response_model=InvoiceResponse)
def parse_invoice(file: UploadFile = File(...)):
    logger.info(f"Received invoice PDF: {file.filename}")
    
    temp_pdf = ARTIFACTS_DIR / f"inv_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}.pdf"
    with open(temp_pdf, "wb") as f:
        f.write(file.file.read())
        
    try:
        images_b64 = _render_pdf_to_images(str(temp_pdf))
        if not images_b64:
            raise HTTPException(status_code=400, detail="PDF contains 0 pages.")
            
        llm_result = _ask_vision_llm_for_invoice(images_b64)
        
        vendor_name = llm_result.get("vendor_name", "")
        raw_line_items = llm_result.get("line_items", [])
        
        processed_items = []
        for raw_item in raw_line_items:
            desc = raw_item.get("description") or ""
            sku = raw_item.get("sku") or ""
            
            # Determine category (fallback to text heuristics if AI failed to output it)
            item_category = raw_item.get("category", "").lower()
            if not item_category:
                desc_lower = desc.lower()
                if "watch" in desc_lower or "mvt" in desc_lower or "movement" in desc_lower or "mm" in desc_lower:
                    item_category = "watch"
                else:
                    item_category = "jewelry"
            
            item_attrs = _build_attributes_from_text_and_vision(
                brand=vendor_name,
                text=desc,
                vision_results=[],
                item_number=sku,
                pre_filled_attrs=None,
                category=item_category
            )
            
            raw_item["attributes"] = item_attrs
            processed_items.append(InvoiceLineItem(**raw_item))
            
        return InvoiceResponse(
            vendor_name=vendor_name,
            invoice_number=llm_result.get("invoice_number"),
            invoice_date=llm_result.get("invoice_date"),
            currency=llm_result.get("currency"),
            line_items=processed_items,
            subtotal=llm_result.get("subtotal"),
            freight=llm_result.get("freight"),
            total=llm_result.get("total"),
            needs_review=llm_result.get("needs_review", False),
            review_reason=llm_result.get("review_reason")
        )
        
    except Exception as e:
        logger.exception("Invoice parsing failed")
        raise HTTPException(status_code=500, detail=f"Invoice parsing failed: {e}")
    finally:
        if temp_pdf.exists():
            temp_pdf.unlink()

# ---------------------------------------------------------------------------
# Windows Service wrapper
# ---------------------------------------------------------------------------
try:
    import win32serviceutil
    import win32service
    import win32event
    import servicemanager
except ImportError:
    pass 

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
            import uvicorn
            uvicorn.run(app, host=API_HOST, port=API_PORT, log_level=LOG_LEVEL.lower())
