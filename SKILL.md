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

## Item Identification

The discovery input is flexible and can include any of these fields:

- `brand`
- `vendor_item_number`
- `upc_code`
- `source_url`

Search priority when multiple identifiers are present:

1. `vendor_item_number`
2. `upc_code`
3. both together for cross-confirmation

If only a UPC is provided, prepend brand/generic qualifiers to the query when searching. If only `vendor_item_number` is provided, search by SKU first. If both are provided, attempt both searches and cross-confirm on matching brand/SKU.

## UPC Validation

When input contains `upc_code`:

1. Query `https://www.upcitemdb.com/upc/<upc_code>`
2. If no record is found or the page indicates no entry, **do not use the UPC for item discovery**.
3. If `vendor_item_number` is also provided, continue item discovery using that vendor item number and ignore the missing UPC. Flag the missing UPC in `confidence.notes`.
4. If only `upc_code` is provided with no record, return a clear message: `UPC <upc_code> not found in UPC Item Database (upcitemdb.com).` and stop.
5. If a record exists, use its findings to cross-confirm or refine product identification before continuing with image/text extraction.
6. If both `vendor_item_number` and `upc_code` are provided, prefer the vendor item lookup path. Use the UPC result only as confirmation; if the UPC points to a different brand/SKU, flag the mismatch in `confidence.notes`.

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
       ...
     },
     "confidence": {
       "overall": "high | medium | low",
       "notes": []
     }
   }
   ```
6. **Confidence notes:** When a parameter is inferred rather than explicitly stated, add a confidence indicator in the value string using format: `"value (inferred)"` or `"value (from text)"`. Use `evidence.images` to track which view supported each field when applicable.

## Site Platform Fallbacks & Pitfalls

- **Demandware / Salesforce Commerce Cloud brands (e.g., David Yurman):** `/products/slug.html` and `/en/product/SKU` may return 404. `/search?q=SKU` often returns empty/404 JSON. Do not assume the brand site is the only source of truth.
- **Authorized retailer fallback:** If the brand PDP is inaccessible, use the Firecrawl `search` tool to locate authorized retailer pages for the exact SKU. Many premium jewelers embed the brand's official CDN images (`static.dy.cloud.bosslogics.com`, etc.) and verified product text. Treat these as trusted secondary sources when:
  - The retailer page explicitly names the brand and SKU.
  - Images resolve to the brand's own image subdomain.
  - Text matches brand-style product descriptions exactly.
- **Image provenance check:** When using retailer-fallback images, verify the image URL host is the brand's CDN rather than the retailer's own uploads. Brand CDN URLs are stronger evidence.
- **Resolved URL caveat:** In the output JSON, `resolved_item_url` may point to a retailer page when the brand PDP was unreachable. Note this in `confidence.notes` so downstream users understand provenance.
- **Text precedence:** Authorized-retailer product text is usually copied from the brand feed. Prefer it over visual inference when it explicitly states metal, stone types, carat weight, or dimensions.
