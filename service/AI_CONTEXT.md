Project Context: Jewelry Attribute Recognition API
1. Overview
Goal: A FastAPI-based service that extracts 31 specific jewelry attributes for Microsoft Dynamics 365 Business Central (BC365). It uses web scraping (Firecrawl) and AI Vision models to analyze product images and text.
Target Stack: Python 3, FastAPI, Uvicorn, PyMuPDF, Pillow, Firecrawl API, Ollama (remote Vision AI on "Spark").
2. Business Workflow (BC Integration)
This service operates in a 2-step workflow orchestrated by Microsoft Business Central:

STEP 1: Invoice Parsing
Input: BC sends a vendor invoice PDF file.
Action: Service converts PDF to images (PyMuPDF) and sends to local Spark AI (qwen3-vl:32b-32k).
Output (JSON): Extracts Vendor Name, Vendor Invoice No, Invoice Date, and Line Items (Vendor Item No, Quantity, Price, Item Description, Item Brand, and as many pre-filled Jewelry Attributes as possible).
STEP 2: Item Enrichment
Input: BC sends the Item Number, Brand, preferred source_url (if found), and the pre_filled_attributes distilled from Step 1.
Action: Service uses Firecrawl to scrape the source_url (or searches if URL is missing), downloads product images, and sends them to Vision AI.
Output (JSON): Fills in any missing attributes that were not found in the invoice text, combining both invoice and web/image data to return the final complete 31-attribute JSON to BC.
3. Architecture & File Structure
api.py: Main FastAPI application. Orchestrates the workflow, defines Pydantic models for BC365, handles PDF parsing, and enforces strict BC365 master data validation.
firecrawl_proxy.py: Standalone Python script run as a subprocess. Queries Firecrawl V2 to search for jewelry products by brand/SKU and scrape text/images.
vision_client.py: Client to communicate with the remote Vision AI server (Ollama, OpenAI-style, or generic). Compresses images to base64 before sending.
config.py: Stores the strict GIA-to-BC365 extraction prompt used for the Vision AI.
requirements.txt: Python dependencies.
4. API Endpoints
POST /api/invoice/parse: Executes Step 1. Accepts PDF, extracts line items & pre-filled attributes.
POST /api/jewelry/recognize: Executes Step 2. Accepts item data + pre-filled attributes, scrapes web/images, returns enriched attributes.
GET /health: Basic health check.
5. Key Logic & Business Rules
31 BC365 Attributes: The system extracts exactly 31 fields (metal_type, center_stone_shape, necklace_type, etc.).
Strict Validation (VALID_BC365_OPTIONS): The AI's output is forced to match exact BC365 master data strings. It uses case-insensitive exact matching, then falls back to the longest substring match. If no match, returns null.
Invoice Pre-fill Priority: If BC sends pre_filled_attributes from Step 1, they are locked in first. The Vision AI in Step 2 only fills fields that the invoice missed.
Multilingual Normalization: Translates French/Italian jewelry terms (e.g., "or rose" -> "18k rose gold", "platine" -> "platinum") before extraction.
GIA to Schema Translation: GIA terms are simplified (e.g., "Round Brilliant" -> "Round").
Image Processing: Images larger than 1024px are compressed and converted to JPEG before being sent to the Vision AI to prevent payload errors.
Firecrawl Fallbacks: If Firecrawl search fails, the system attempts direct URL construction for known brands (Cartier, Tiffany, David Yurman) or falls back to UPC database.
6. Environment Variables
FIRECRAWL_API_KEY: Required for web scraping.
VISION_API_URL: URL for the Ollama/Vision server (default http://localhost:11434).
VISION_MODEL: Default model (e.g., llava).
INVOICE_VISION_MODEL: Model for PDF parsing (default qwen3-vl:32b-32k).
JEWELRY_API_PORT: Default 8000.
7. Rules for AI Assistant
Always maintain the strict BC365 schema. Do not invent new fields or valid options.
When modifying API endpoints, ensure the Pydantic models match the expected BC365 payload.
Preserve the _normalize_to_bc365 strict matching logic.
Ensure firecrawl_proxy.py remains a standalone script executed via subprocess.run.
Remember the 2-step Business Workflow: Step 1 (Invoice) feeds pre-filled attributes to Step 2 (Enrichment).
8. Current State & Progress
Core workflow is functional.
Invoice parsing uses Vision AI (qwen3-vl) instead of just text OCR.
Attribute extraction runs on both invoice text and web-scraped text/images.
Windows Service wrapper is present but currently disabled in favor of Task Scheduler (python.exe api.py).