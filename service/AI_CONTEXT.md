Project Context: Jewelry Attribute Recognition API
1. Overview
Goal: A FastAPI-based service that extracts 31 specific jewelry attributes for Microsoft Dynamics 365 Business Central (BC365). It uses web scraping (Firecrawl) and AI Vision models to analyze product images and text.
Target Stack: Python 3, FastAPI, Uvicorn, PyMuPDF, Pillow, Firecrawl API, Ollama (remote Vision AI on "Spark").
Deployment: Code is modified on a laptop in VS Code, pushed to GitHub, and deployed on a Windows Server 2025 via a PowerShell script (deploy.ps1) that pulls code and restarts a Scheduled Task.
2. Business Workflow (BC Integration)
This service operates in a 2-step workflow orchestrated by Microsoft Business Central:

STEP 1: Invoice Parsing (POST /api/invoice/parse)
Input: BC sends a vendor invoice PDF file.
Action: Service converts PDF to images (PyMuPDF) and sends to local Spark AI (qwen3-vl:32b-32k via Ollama).
Output (JSON): Extracts Vendor Name, Invoice No, Date, and Line Items (SKU, Alternate SKU, Description, Brand, Qty, Unit, Price, and pre-filled Jewelry Attributes).
STEP 2: Item Enrichment (POST /api/jewelry/recognize)
Input: BC sends the Item Number, Brand, preferred source_url (if found), and the pre_filled_attributes distilled from Step 1.
Action: Service uses Firecrawl to scrape the source_url (or searches if URL is missing), downloads product images, and sends them to Vision AI.
Output (JSON): Fills in any missing attributes that were not found in the invoice text, combining both invoice and web/image data to return the final complete 31-attribute JSON to BC.
3. Architecture & File Structure
api.py: Main FastAPI application. Orchestrates the workflow, defines Pydantic models for BC365, handles PDF parsing, and enforces strict BC365 master data validation.
firecrawl_proxy.py: Standalone Python script run as a subprocess. Queries Firecrawl V2 to search for jewelry products by brand/SKU and scrape text/images.
vision_client.py: Client to communicate with the remote Vision AI server (Ollama, OpenAI-style, or generic). Compresses images to base64 before sending.
config.py: Stores the strict GIA-to-BC365 extraction prompt used for the Vision AI.
requirements.txt: Python dependencies.
4. Key Logic & Business Rules
31 BC365 Attributes: The system extracts exactly 31 fields (metal_type, center_stone_shape, necklace_type, etc.).
Strict Validation (VALID_BC365_OPTIONS): The AI's output is forced to match exact BC365 master data strings. It uses case-insensitive exact matching, then falls back to the longest substring match. If no match, returns null.
Invoice Pre-fill Priority: If BC sends pre_filled_attributes from Step 1, they are locked in first. The Vision AI in Step 2 only fills fields that the invoice missed.
Smart PDF Filtering (_render_pdf_to_images):
Scans raw text of each PDF page. Skips pages containing legal keywords (e.g., "Terms & Conditions", "Warranty", "Governing Law").
Skips pages that do not contain at least 2 price patterns (e.g., "$123.45").
Hard-limits extraction to the first 2 valid invoice pages to prevent Vision AI timeouts.
Renders valid pages at 150 DPI.
Vision AI Timeout: The timeout for Ollama during invoice parsing is set to 600 seconds (10 minutes) to accommodate large models processing dense invoices.
Multilingual Normalization: Translates French/Italian jewelry terms (e.g., "or rose" -> "18k rose gold") before extraction.
Firecrawl Fallbacks: If Firecrawl search fails, the system attempts direct URL construction for known brands (Cartier, Tiffany, David Yurman) or falls back to UPC database.
5. Environment Variables
FIRECRAWL_API_KEY: Required for web scraping.
VISION_API_URL: URL for the Ollama/Vision server (e.g., http://100.88.93.128:11434).
VISION_MODEL: Default model (e.g., llava).
INVOICE_VISION_MODEL: Model for PDF parsing (default qwen3-vl:32b-32k).
JEWELRY_API_PORT: Default 8000.
6. Rules for AI Assistant
Always maintain the strict BC365 schema. Do not invent new fields or valid options.
When modifying API endpoints, ensure the Pydantic models match the expected BC365 payload.
Preserve the _normalize_to_bc365 strict matching logic.
Ensure firecrawl_proxy.py remains a standalone script executed via subprocess.run.
Remember the 2-step Business Workflow: Step 1 (Invoice) feeds pre-filled attributes to Step 2 (Enrichment).
7. Current State & Progress
Step 1 (Invoice Parsing) is FULLY WORKING and TESTED. Successfully tested with John Hardy and Quality Gold PDFs. Correctly extracts Brand, SKU, Prices, and pre-fills basic attributes (metal_type, product_type, center_stone_type).
Step 2 (Item Enrichment) code is functional but has not been explicitly tested in this session yet.
Windows Service wrapper is present but currently disabled in favor of Task Scheduler (python.exe api.py).