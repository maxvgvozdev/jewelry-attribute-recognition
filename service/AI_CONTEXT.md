Project Context: Jewelry Attribute Recognition API
1. How to Transfer Context to a New Chat
To resume work on this project in a new AI chat (without losing state), paste this AI_CONTEXT.md file first. Then, paste the contents of the following files from your GitHub repository:

service/api.py (Main FastAPI application, Pydantic models, PDF parsing, BC365 strict validation logic).
service/firecrawl_proxy.py (Standalone script for Firecrawl V2 web search/scraping).
service/vision_client.py (Client for communicating with Spark AI / Ollama).
service/config.py (Vision AI extraction prompt).
service/requirements.txt (Python dependencies).
service/deploy.ps1 (PowerShell deployment script for Production).
service/deploy_test.ps1 (PowerShell deployment script for Testing).
Prompt to use in the new chat: "Here is my AI_CONTEXT.md file and the associated project code. Read this to understand our project state. Do not write any code yet, just acknowledge."

2. Overview
Goal: A FastAPI-based service that extracts specific jewelry (and soon, watch) attributes for Microsoft Dynamics 365 Business Central (BC365). It uses web scraping (Firecrawl) and AI Vision models (Ollama) to analyze product images and text.
Target Stack: Python 3, FastAPI, Uvicorn, PyMuPDF, Pillow, Firecrawl API, Ollama (remote Vision AI on "Spark").
Deployment: Code is modified on a laptop in VS Code, pushed to GitHub, and deployed on a Windows Server 2025 via PowerShell scripts that pull code and restart Scheduled Tasks.
3. Dual-Instance Architecture (Server Setup)
To develop new features safely, the Windows Server runs two instances of the service simultaneously:

Production Instance:
Folder: C:\Deploy\jewelry-attribute-recognition\service
Port: 8000
Script: deploy.ps1
Task Scheduler: JewelryAgentAPI
Used for: Live Business Central integration.
Test Instance:
Folder: C:\Deploy\jewelry-attribute-recognition-test\service
Port: 8001
Script: deploy_test.ps1
Task Scheduler: JewelryAgentAPI_Test
Used for: Testing new features (like Watch support) before promoting to Production.
4. Business Workflow (BC Integration)
This service operates in a 2-step workflow orchestrated by Microsoft Business Central:

STEP 1: Invoice Parsing (POST /api/invoice/parse)
Input: BC sends a vendor invoice PDF file.
Action: Service converts PDF to images (PyMuPDF) and sends to local Spark AI (default:latest via Ollama at 100.88.93.128:11434).
Output (JSON): Extracts Vendor Name, Invoice No, Date, and Line Items (SKU, Alternate SKU, Description, Brand, Qty, Unit, Price, and pre-filled Jewelry Attributes).
STEP 2: Item Enrichment (POST /api/jewelry/recognize)
Input: BC sends the Item Number, Brand, preferred source_url (if found), and the pre_filled_attributes distilled from Step 1.
Action: Service uses Firecrawl to scrape the source_url (or searches if URL is missing), downloads product images, and sends them to Vision AI.
Output (JSON): Fills in any missing attributes that were not found in the invoice text, combining both invoice and web/image data to return the final complete attribute JSON to BC.
5. Key Logic & Business Rules
31 BC365 Attributes: The system currently extracts exactly 31 fields (metal_type, center_stone_shape, necklace_type, etc.).
Strict Validation (VALID_BC365_OPTIONS): The AI's output is forced to match exact BC365 master data strings. It uses case-insensitive exact matching, then falls back to the longest substring match. If no match, returns null.
Invoice Pre-fill Priority: If BC sends pre_filled_attributes from Step 1, they are locked in first. The Vision AI in Step 2 only fills fields that the invoice missed.
Text vs JSON Separation: api.py passes only page_text (not the Vision AI's JSON response) to the text heuristic scanner to prevent JSON keys (like "engagement_ring_type") from falsely triggering product type categorization.
Smart PDF Filtering (_render_pdf_to_images):
Scans raw text of each PDF page. Skips pages containing legal keywords (e.g., "Terms & Conditions", "Warranty", "Governing Law").
Skips pages that do not contain at least 2 price patterns (e.g., "$123.45").
Hard-limits extraction to the first 2 valid invoice pages to prevent Vision AI timeouts.
Renders valid pages at 150 DPI.
Vision AI Timeout: The timeout for Ollama during invoice parsing is set to 600 seconds (10 minutes) to accommodate large models processing dense invoices.
Multilingual Normalization: Translates French/Italian jewelry terms (e.g., "or rose" -> "18k rose gold") before extraction.
Firecrawl Fallbacks: If Firecrawl search fails, the system attempts direct URL construction for known brands (Cartier, Tiffany, David Yurman) or falls back to UPC database.
6. Environment Variables
FIRECRAWL_API_KEY: Required for web scraping.
VISION_API_URL: URL for the Ollama/Vision server (e.g., http://100.88.93.128:11434).
INVOICE_VISION_MODEL: Model for PDF parsing (default default:latest, which points to a local Qwen multimodal model on Spark).
VISION_MODEL: Model for image analysis (default default:latest).
JEWELRY_API_PORT: Default 8000 (Prod), 8001 (Test).
JEWELRY_API_HOST: Default 0.0.0.0.
7. Rules for AI Assistant
Always maintain the strict BC365 schema. Do not invent new fields or valid options without explicit instruction.
When modifying API endpoints, ensure the Pydantic models match the expected BC365 payload.
Preserve the _normalize_to_bc365 strict matching logic.
Ensure firecrawl_proxy.py remains a standalone script executed via subprocess.run.
Remember the 2-step Business Workflow: Step 1 (Invoice) feeds pre-filled attributes to Step 2 (Enrichment).
When writing AL code for Business Central, always use HttpClient.Timeout(600000) because Vision AI takes longer than BC's default 100s timeout.
8. Current State & Progress
Step 1 (Invoice Parsing) is FULLY WORKING and TESTED. Smart T&C filtering prevents AI timeouts. Correctly extracts Brand, SKU, Prices, and pre-fills basic attributes.
Step 2 (Item Enrichment) is FULLY WORKING and TESTED. Firecrawl finds images, Vision AI fills missing attributes. Fixed bug where Vision JSON keys falsely triggered text heuristics.
BC Integration AL Code is FINALIZED. AL codeunit includes Step 1 (PDF Multipart upload) and Step 2 (JSON Enrichment). Background Job Queue architecture documented.
NEXT PHASE: Adding functionality to distill attributes for Watches. Development and testing of this feature will take place on the Test Instance (Port 8001) before moving to Production.
