---
name: jewelry-attribute-recognition
description: |
  Complete jewelry item parameter schema for image/text recognition.
  Use this skill when the user wants to identify, classify, or extract
  jewelry attributes from images, text descriptions, or product data.
  Covers metals, stones, product types, settings, themes, and finishing.
  Trigger: "jewelry", "ring", "earring", "necklace", "bracelet",
  "gemstone", "diamond", "engagement", "wedding band", "metal type".
---

# Jewelry Attribute Recognition

## Overview

This skill defines the **exact and complete list of jewelry item parameters** to be revealed during recognition tasks.

The schema is based on the source file:
`C:\Users\Магистр\Downloads\AI Master Data Attributes 1.xlsx` — Sheet: *Jewelry Attributes*

**Primary reference for jewelry recognition:** `C:\Users\Магистр\Downloads\GIA-Jewelry-Reference-Guide-UPDATED.pdf`
For image analysis and parameter reveal, follow GIA terminology and classifications in this guide first.

---

## Output Schema (31 fields)

When recognizing or describing a jewelry item, always return values for **all applicable fields** below, in this order.

| # | Parameter | Type | Notes |
|---|-----------|------|-------|
| 1 | Metal Type | Options | Alloys and materials (see `references/metal-types.md`) |
| 2 | Metal Color | Options | Finish/color of metal |
| 3 | Stone Primary Color | Options | Dominant gemstone color |
| 4 | Product Type | Options | Broad category (ring, earring, etc.) |
| 5 | Gender | Options | Baby / Gents / Ladies / Unisex / blank |
| 6 | Center Stone Type | Options | Main gem material |
| 7 | Center Stone Shape | Options | Cut/shape of center stone |
| 8 | 1st Side Stone Type | Options | First accent gem material |
| 9 | 1st Side Stone Shape | Options | First accent cut/shape |
| 10 | 2nd Side Stone Type | Options | Second accent gem material |
| 11 | 2nd Side Stone Shape | Options | Second accent cut/shape |
| 12 | Engagement Set Type | Options | Engagement-related set category |
| 13 | Engagement Ring Type | Options | Halo / Solitaire / Three Stone / etc. |
| 14 | Wedding Band Type | Options | Antique / Classic / Contemporary / etc. |
| 15 | Wedding Band Setting Type | Options | Channel / Pave / Prong / Bezel / etc. |
| 16 | Wedding Band Stone Continuity | Options | Eternity / Half Way / Three Quarter / Separated / Religious / Solitaire |
| 17 | Fashion Ring Type | Options | Cocktail Ring / Halo / Cluster / etc. |
| 18 | Earring Type | Options | Stud / Hoops / Dangle / Huggies / etc. |
| 19 | Necklace Type | Options | Chain / Pendant / Strand / Lariat / etc. |
| 20 | Bracelet Type | Options | Bangle / Bead / Cable / Cuff / etc. |
| 21 | Accessory Type | Options | Brooch / Tie Bar / Cufflink / Keychain / etc. |
| 22 | Theme | Options | Animal / Flower / Love / Nature / etc. |
| 23 | Occasion | Options | Anniversary / Birthday / Engagement / etc. |
| 24 | Jewelry Shape | Options | Round / Oval / Heart / Cross / etc. |
| 25 | Motif | Options | Leaf / Star / Hamsa / Infinity / etc. |
| 26 | Finishing Type | Options | Polished / Brushed / Hammered / Satin / Milgrain / etc. |
| 27 | Estate Period | Options | Victorian / Art Deco / Retro / etc. |
| 28 | Holiday Code | Options | Christmas / Valentine's / Halloween / etc. |
| 29 | Chain Type | Options | Rope / Cable / Box / Figaro / etc. |
| 30 | Clasp Type | Options | Lobster / Spring Ring / Toggle / Magnetic / etc. |
| 31 | Earring Back | Options | Omega / Screwback / Push / Leverback / etc. |

---

## Recognition Rules

1. **Reveal all applicable fields.** If a field is not determinable from the image/text, set it to `null` or `N/A`.
2. **Use exact option values** from the source lists. Do not paraphrase or invent new values.
3. **If multiple options fit**, prefer the most specific match.
4. **For image recognition**, prioritize visual cues:
   - Metal → color, shine, hallmark clues
   - Stone → color, cut, setting style
   - Product type → overall silhouette and wear style
5. **For text/product descriptions**, parse explicit mentions first.

---

## Reference Files

Allowed values and visual-to-parameter mapping are in the `references` folder under this skill:

- `visual-mappings.md` — structured mappings from image/text cues to 31 jewelry parameters (use this first)
- `metal-types.md` — metal alloys and colors
- `stone-types.md` — gemstone and pearl taxonomy
- `product-types.md` — product type taxonomy
- `setting-types.md` — ring settings, prongs, melee
- `themes-motifs.md` — themes, motifs, occasions
- `finishing.md` — finishing and design details
- `chain-clasp-earring-back.md` — chains, clasps, earring backs

## External Tooling: Firecrawl (optional)

If brand-site discovery requires JavaScript-rendered pages, use the bundled proxy script instead of raw HTML fetch:

- Script: `scripts/firecrawl_proxy.py`
- Config: create `firecrawl_config.json` at the skill root with `{ "api_key": "<key>" }`, or set `FIRECRAWL_API_KEY`
- Commands: `search <query>`, `scrape <url>`, `crawl <url> [limit]`
- Output: JSON to stdout

If Firecrawl is not configured, the agent will fall back to direct HTTP extraction where possible.

## Recognition Pipeline

1. If an image/photo is provided, compare it against relevant GIA diagram pages in `references/assets/`.
2. Apply the structured mappings in `references/visual-mappings.md`.
3. Return all 31 parameters in canonical order.
4. Use exact option values where applicable; otherwise `null`.

## Brand Site Workflow

When the user provides brand, item number, and a brand site start URL:

1. **Item page discovery:** Use the brand site to search for the item page using the provided `item_number`. The `source_url` is a starting point only; the agent must navigate/search within that brand domain.
2. **Image collection:** Once the item page is found, collect exactly **3 product images** from it:
   - Primary front view
   - Side/detail view
   - Additional view/context shot
3. **Text extraction:** Extract all visible product text from the item page, including:
   - Title/product name
   - Material descriptions
   - Gemstone/specifications
   - Dimensions/measurements
4. **Combined analysis:** Use BOTH images and text together:
   - Text descriptions override visual inference when available
   - Images confirm or refine text-based classifications
   - Cross-reference with GIA diagrams in `references/assets/`
5. **Output format:** Always return JSON with evidence plus the 31 parameters in canonical order:
   ```json
   {
     "item": {
       "brand": "Cartier",
       "vendor_item_number": "B6081517",
       "source_url": "https://www.cartier.com/en-us/home",
       "resolved_item_url": "https://www.cartier.com/en-us/jewelry/bracelets/love/love-bracelet-medium-model-B6081517.html"
     },
     "evidence": {
       "images": [
         {
           "url": "https://...",
           "view_type": "front",
           "alt_text": "Front view"
         }
       ],
       "text": "Excerpted product text from the item page"
     },
     "attributes": {
       "metal_type": "...",
       "metal_color": "...",
       "stone_primary_color": "...",
       "product_type": "...",
       "gender": "...",
       "center_stone_type": "...",
       "center_stone_shape": "...",
       "side_stone_1_type": "...",
       "side_stone_1_shape": "...",
       "side_stone_2_type": "...",
       "side_stone_2_shape": "...",
       "engagement_set_type": "...",
       "engagement_ring_type": "...",
       "wedding_band_type": "...",
       "wedding_band_setting_type": "...",
       "wedding_band_stone_continuity": "...",
       "fashion_ring_type": "...",
       "earring_type": "...",
       "necklace_type": "...",
       "bracelet_type": "...",
       "accessory_type": "...",
       "theme": "...",
       "occasion": "...",
       "jewelry_shape": "...",
       "motif": "...",
       "finishing_type": "...",
       "estate_period": "...",
       "holiday_code": "...",
       "chain_type": "...",
       "clasp_type": "...",
       "earring_back": "..."
     },
     "confidence": {
       "overall": "high | medium | low",
       "notes": []
     }
   }
   ```
6. **Confidence notes:** When a parameter is inferred rather than explicitly stated, add a confidence indicator in the value string using format: `"value (inferred)"` or `"value (from text)"`. Use `evidence.images` to track which view supported each field when applicable.
