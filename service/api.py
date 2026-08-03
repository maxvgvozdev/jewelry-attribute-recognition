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

def _run_firecrawl_scrape(url: str) -> Dict[str, Any]:
    """Directly scrape a URL using the Firecrawl proxy script."""
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


def _normalize_to_bc365(field: str, raw_value: Any) -> Optional[str]:
    """
    Forces a raw extracted string to match the EXACT valid BC365 Master Data option.
    Uses case-insensitive exact matching, then longest-substring fallback for synonyms.
    """
    if not raw_value or not isinstance(raw_value, str):
        return None
        
    valid_options = VALID_BC365_OPTIONS.get(field)
    if not valid_options:
        return None
        
    raw_clean = raw_value.strip()
    raw_lower = raw_clean.lower()
    
    # 1. Exact match (case-insensitive)
    for opt in valid_options:
        if opt.lower() == raw_lower:
            return opt
            
    # 2. Substring match (e.g. LLM says "Stud Earrings", we map it to "Stud")
    # We pick the longest valid option that matches to avoid "White" matching when "18K White Gold" is better
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
            
        vision_attrs = _extract_json_from_text(analysis_text)
        
        if vision_attrs and isinstance(vision_attrs, dict):
            for key, value in vision_attrs.items():
                if key in attrs and value is not None:
                    # FORCE VISION AI RESULTS THROUGH STRICT VALIDATOR
                    attrs[key] = _normalize_to_bc365(key, str(value))

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
    # Map "brilliant-cut" to "round" so shape extraction works
    if "taille brillant" in text_lower or "brilliant-cut" in text_lower:
        text_lower = text_lower.replace("taille brillant", "round").replace("brilliant-cut", "round")
    if "taille baguette" in text_lower:
        text_lower = text_lower.replace("taille baguette", "baguette")

    # -----------------------------------------------------------------------
    # 4. STONE EXTRACTION (Handling multiple stones like "Gold with Peridot and Diamonds")
    # -----------------------------------------------------------------------
    mentioned_stones = []
    for stone in VALID_BC365_OPTIONS.get("center_stone_type", set()):
        if stone.lower() in ("other gemstones", "no stone", "enamel", "glass", "resin (plastic)"):
            continue
        if stone.lower() in text_lower:
            mentioned_stones.append(stone)

    if mentioned_stones:
        first_stone_idx = len(text_lower)
        first_stone = mentioned_stones[0]
        for s in mentioned_stones:
            idx = text_lower.find(s.lower())
            if idx != -1 and idx < first_stone_idx:
                first_stone_idx = idx
                first_stone = s

        if not attrs.get("center_stone_type"):
            if len(mentioned_stones) > 1 and "Diamond" in mentioned_stones:
                if "with diamond" in text_lower or "and diamond" in text_lower:
                    for s in mentioned_stones:
                        if s != "Diamond":
                            attrs["center_stone_type"] = _normalize_to_bc365("center_stone_type", s)
                            break
                else:
                    attrs["center_stone_type"] = _normalize_to_bc365("center_stone_type", first_stone)
            else:
                attrs["center_stone_type"] = _normalize_to_bc365("center_stone_type", first_stone)

        if not attrs.get("side_stone_1_type"):
            # FIX: If text says "paved with diamonds" or "halo of diamonds", assume side stone is Diamond
            if ("paved" in text_lower or "pave" in text_lower or "halo" in text_lower) and attrs.get("center_stone_type") == "Diamond":
                attrs["side_stone_1_type"] = "Diamond"
            else:
                for s in mentioned_stones:
                    if s != attrs.get("center_stone_type"):
                        attrs["side_stone_1_type"] = _normalize_to_bc365("side_stone_1_type", s)
                        break

    # -----------------------------------------------------------------------
    # 5. COLOR & SHAPE EXTRACTION
    # -----------------------------------------------------------------------
    if not attrs.get("stone_primary_color"):
        if "peridot" in text_lower:
            attrs["stone_primary_color"] = _normalize_to_bc365("stone_primary_color", "Green")
        elif "ruby" in text_lower or "garnet" in text_lower:
            attrs["stone_primary_color"] = _normalize_to_bc365("stone_primary_color", "Red")
        elif "sapphire" in text_lower:
            attrs["stone_primary_color"] = _normalize_to_bc365("stone_primary_color", "Blue")
        elif "emerald" in text_lower:
            attrs["stone_primary_color"] = _normalize_to_bc365("stone_primary_color", "Green")
        elif "diamond" in text_lower:
            attrs["stone_primary_color"] = _normalize_to_bc365("stone_primary_color", "White")

    if not attrs.get("center_stone_shape") and "round" in text_lower:
        attrs["center_stone_shape"] = _normalize_to_bc365("center_stone_shape", "Round")

    # -----------------------------------------------------------------------
    # 6. MATERIAL & CATEGORY OVERRIDES
    # -----------------------------------------------------------------------
    if "18k rose gold" in text_lower or "18-karat rose gold" in text_lower:
        attrs["metal_type"] = _normalize_to_bc365("metal_type", "18K Rose Gold")
        attrs["metal_color"] = _normalize_to_bc365("metal_color", "Rose")
    elif "18k white gold" in text_lower or "18-karat white gold" in text_lower:
        attrs["metal_type"] = _normalize_to_bc365("metal_type", "18K White Gold")
        attrs["metal_color"] = _normalize_to_bc365("metal_color", "White")
    elif "18k yellow gold" in text_lower or "18-karat yellow gold" in text_lower:
        attrs["metal_type"] = _normalize_to_bc365("metal_type", "18K Yellow Gold")
        attrs["metal_color"] = _normalize_to_bc365("metal_color", "Yellow")

    if "platinum" in text_lower:
        attrs["metal_color"] = _normalize_to_bc365("metal_color", "White")

    if not attrs.get("product_type"):
        if "solitaire" in text_lower and "diamond" in text_lower:
            attrs["product_type"] = _normalize_to_bc365("product_type", "Engagement Rings")
        elif "engagement" in text_lower:
            attrs["product_type"] = _normalize_to_bc365("product_type", "Engagement Rings")
        elif "bague" in text_lower or "anello" in text_lower or "anillo" in text_lower:
            if "wedding" not in text_lower and "engagement" not in text_lower:
                attrs["product_type"] = _normalize_to_bc365("product_type", "Fashion Rings")
        elif "earring" in text_lower:
            attrs["product_type"] = _normalize_to_bc365("product_type", "Earrings")
        elif "necklace" in text_lower or "pendant" in text_lower:
            attrs["product_type"] = _normalize_to_bc365("product_type", "Necklaces")
        elif "bracelet" in text_lower or "bangle" in text_lower:
            attrs["product_type"] = _normalize_to_bc365("product_type", "Bracelets")
        elif "wedding band" in text_lower:
            attrs["product_type"] = _normalize_to_bc365("product_type", "Wedding Bands")
        elif "ring" in text_lower:
            attrs["product_type"] = _normalize_to_bc365("product_type", "Fashion Rings")

    if not attrs.get("engagement_ring_type") and "solitaire" in text_lower:
        attrs["engagement_ring_type"] = _normalize_to_bc365("engagement_ring_type", "Solitaire")
        
    if "pavé" in text_lower or "pave" in text_lower or "paved" in text_lower:
        if not attrs.get("wedding_band_setting_type"):
            attrs["wedding_band_setting_type"] = _normalize_to_bc365("wedding_band_setting_type", "Pave")

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
        # SMART FALLBACK: If Firecrawl search fails, construct the URL natively 
        # for known luxury brands that have predictable URL structures.
        brand_lower = brand.lower()
        item_to_use = vendor_item_number or upc_code
        
        if brand_lower == 'cartier' and item_to_use:
            resolved_url = f"https://www.cartier.com/en-us/jewelry/-/{item_to_use}.html"
            confidence_notes.append(f"Firecrawl search failed. Dynamically constructed Cartier URL: {resolved_url}")
        elif brand_lower == 'tiffany' and item_to_use:
            resolved_url = f"https://www.tiffany.com/jewelry/-/{item_to_use}"
            confidence_notes.append(f"Firecrawl search failed. Dynamically constructed Tiffany URL: {resolved_url}")
        elif brand_lower == 'david yurman' and item_to_use:
            # David Yurman often uses formats like R18647D88.html
            resolved_url = f"https://www.davidyurman.com/-{item_to_use}.html"
            confidence_notes.append(f"Firecrawl search failed. Dynamically constructed DY URL: {resolved_url}")
        elif upc_code:
            resolved_url = f"https://www.upcitemdb.com/upc/{upc_code}"
            confidence_notes.append(f"Firecrawl search failed. Falling back to UPC database.")
        else:
            raise HTTPException(
                status_code=404, 
                detail=f"Firecrawl found 0 search results for '{brand} {vendor_item_number}'. "
                       f"Please provide the exact 'source_url' parameter in the payload."
            )
    # -----------------------------------------------------------------------
    # SCRAPE FALLBACK: If we have a URL but NO images (e.g., Smart Fallback triggered),
    # we must explicitly scrape the URL to get text and images.
    # -----------------------------------------------------------------------
    if not image_urls and resolved_url:
        try:
            confidence_notes.append(f"Search yielded no images. Attempting direct scrape of: {resolved_url}")
            scrape_result = _run_firecrawl_scrape(resolved_url)
            scrape_items = scrape_result.get("data", [])
            
            if scrape_items:
                # Update text if the search didn't find any
                if not page_text:
                    page_text = scrape_items[0].get("description", "") or ""
                
                # Grab the images
                image_urls = scrape_items[0].get("images", [])
                if image_urls:
                    confidence_notes.append("Direct scrape fallback successfully extracted product images.")
        except Exception as exc:
            confidence_notes.append(f"Direct scrape fallback failed: {exc}")

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