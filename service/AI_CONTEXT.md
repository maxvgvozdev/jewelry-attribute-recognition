Project Context: Jewelry & Watch Attribute Recognition API
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
Goal: A FastAPI-based service that extracts specific jewelry AND watch attributes for Microsoft Dynamics 365 Business Central (BC365). It uses web scraping (Firecrawl) and AI Vision models (Ollama) to analyze product images and text.
Target Stack: Python 3, FastAPI, Uvicorn, PyMuPDF, Pillow, Firecrawl API, Ollama (remote Vision AI on "Spark").
Deployment: Code is modified on a laptop in VS Code, pushed to GitHub, and deployed on a Windows Server 2025 via PowerShell scripts that pull code and restart Scheduled Tasks.
3. Dual-Instance Architecture (Server Setup)
To develop new features safely, the Windows Server runs two instances of the service simultaneously:

Production Instance: Folder: C:\Deploy\jewelry-attribute-recognition\service | Port: 8000 | Script: deploy.ps1 | Task: JewelryAgentAPI (Live BC integration).
Test Instance: Folder: C:\Deploy\jewelry-attribute-recognition-test\service | Port: 8001 | Script: deploy_test.ps1 | Task: JewelryAgentAPI_Test (Used for testing new features like Watch support).
4. Business Workflow (BC Integration)
This service operates in a 2-step workflow orchestrated by Microsoft Business Central:

STEP 1: Invoice Parsing (POST /api/invoice/parse) - BC sends a vendor invoice PDF. Service extracts Vendor Info, Line Items, and pre-filled attributes.
STEP 2: Item Enrichment (POST /api/jewelry/recognize) - BC sends Item Number, Brand, URL, and pre-filled attributes. Service scrapes web/images and fills missing attributes.
5. Key Logic & Business Rules
Category Routing: The service will route logic based on a category field (jewelry or watch).
Strict Validation: The AI's output is forced to match exact BC365 master data strings. Case-insensitive exact matching, then longest substring match. If no match, returns null.
Invoice Pre-fill Priority: Pre-filled attributes from Step 1 are locked in first. Vision AI in Step 2 only fills missing fields.
Smart PDF Filtering (_render_pdf_to_images): Skips legal/T&C pages and limits to 2 pages to prevent AI timeouts.
Vision AI: Uses default:latest (local Qwen multimodal on Spark) for both PDF parsing and image analysis. Timeout is 600s.
6. BC365 Schema: Jewelry (31 Attributes)
Extracts: metal_type, metal_color, stone_primary_color, product_type, gender, center_stone_type, center_stone_shape, side_stone_1_type, side_stone_1_shape, side_stone_2_type, side_stone_2_shape, engagement_set_type, engagement_ring_type, wedding_band_type, wedding_band_setting_type, wedding_band_stone_continuity, fashion_ring_type, earring_type, necklace_type, bracelet_type, accessory_type, theme, occasion, jewelry_shape, motif, finishing_type, estate_period, holiday_code, chain_type, clasp_type, earring_back.

7. BC365 Schema: Watches (40+ Attributes & Valid Options)
Extracts: functions_complications, watch_style, movement_type, display_type, case_diameter, case_thickness_mm, case_shape, dial_color, case_back, dial_motif, watch_display_number_type, dial_embellishment, case_material, strap_bracelet_type, strap_bracelet_material, case_color, strap_color, strap_secondary_color, strap_bracelet_width_mm, crystal_material, special_functions, power_reserve_hour, water_resistance_m, clasp_type, watch_brand, watch_collection, bezel_type, winding_crown, calibre, precision, certification, gender, msrp_price, year_produced, limited_production, watch_size, treatment.

Valid Watch Options (Strict BC365 Mapping):
functions_complications: Date, Day, Centre Hour, Instantaneous Date, Minute and Second Hand, Stop-seconds for precise time setting, Power Reserve, Month, Moon Phase, Second Hand, Chronograph, Chronometer, minute repeater, perpetual calendar, alarm, split chronometer, annual calendar, tourbillon, GMT, World Time
watch_style: Casual, Dress, Fashion, Luxury, Sport, Diver, Pocket
movement_type: Automatic, Hand, Quartz, Manual, Spring Drive, Self Winding, Solar, Eco-Drive, Mechanical/Manual, Automatic AND Manual, Automatic/Self Winding
display_type: Analog, Analog/Digital, Digital, LED, 1 Subdial, 2 Subdial, 3 Subdial
case_shape: Heart, Oval, Rectangular, Round, Square, Tonneau, Triangular, Cushion, Other
dial_color: Beige, Black, Blue, Blue/Black, Blue/Red, Brown, Burgundy, Champagne, Chocolate/Black, Gold, Gray, Green, Ivory, Maroon, Not Applicable, Navy Blue, Onyx, Orange, Pink, Purple, Red, Rose Gold, Silver, Turquoise, Violet, White, Yellow, Yellow Gold, Slate, Red Grape, Black Mother of Pearl, Blue Mother of Pearl, Cream, Golden, Grey Mother of Pearl, Multi Color, Pink Mother of Pearl, Skeleton, White Mother of Pearl, Diamond, Reverso
case_back: Closed, Open, Skeleton
dial_motif: Celebration, Eisenkiesel, Floral, Fluted, Meteorite, Mother Of Pearl, Palm, Pave Diamonds and Sapphires, Pave Diamonds, No Motf/Plain Color
watch_display_number_type: A/Dot, Arabic and Index, Arabic and Roman, Arabic, Colored Stone/Crystal, Diamond, Diamond and Arabic, Diamond and Dot, Diamond and Index, Diamond and Roman, Digital, Dot, Dot and Index, Index and Colored Stone/Crystal, Index and Roman, Index, Roman and Colored Stone/Crystal, Roman, Dot and Roman
dial_embellishment: Crystal, Diamonds, Gemstone, Glitter, Pearl, Rhinestone, Stud
case_material: Gold 14K, Gold 18K, Platinum, Silver, Stainless Steel, Rolesor 18 Carat, Rolesium Platinum, Titanium, PVD, Bronze, Breitlight, Ceramic, Carbon Fiber, Diamond Like Carbon, Platinum and Stainless Steel, Polymer/Plastic, Rose Gold, Rose Gold and Platinum, Rose Gold and Stainless Steel, Rose Tone, Rose Tone and Stainless Steel, Stainless Steel and Blue Tone, Stainless Steel and Black PVD, Stainless Steel and Brass, Stainess Steel and Bronze, Stainless Steeel and Black Tone, Stainless Steel and Ceramic, Stainless Steel and Carbon Fiber, Stainless Steel and Titanium Coating, Tungsten Carbide, Tantalum, White Gold Rhodium Plated, White Gold Rhodium Plated and Platinum, White Gold Rhodium Plated and Stainless Steel, Yellow Gold, Yellow Gold and Platinum, Yellow Gold and Stainless Steel, Yellow Tone, Yellow Tone and Stainless Steel, Ceratanium
strap_bracelet_type: Bangle, Bracelet, Bracelet and Strap, Cuff, Strap, Bracelet and 2 Straps, Strap Set of 2, Strap Set of 3, Strap Set of 5
strap_bracelet_material: Gold 14K, Gold 18K, Alligator Leather, Platinum, Leather, Silver, Stainless Steel, Rolesor 18 Carat, Rolesium Platinum, Titanium, Calfskin, Sharkskin, Ostrich, Crocodile, Elastomer, Silicone, Rubber, Nylon, Cloth, Canvas, Lizard, Pig, Kevlar, Cordura, Carbon Fiber, Lamb Skin, Ceramic, Appleskin, Fabric, Fabric and Leather, Grosgrain, Leather and Nylon Set of 2, Grain, Microfiber, PVD, Satin, Snakeskin, Textile, Vegan Leather, Oysterflex, cord, Bronze, Diamond Like Carbon, Platinum, Polymer/Plastic, PVD, Rose Gold, Rose Gold and Platinum, Rose Gold and Stainless Steel, Rose Tone, Rose Tone and Ceramic, Rose Tone and Stainless Steel, Sterling Silver Plated Product, Stainess Steel and Blue Tone, Stainless Steel and Black PVD, Stainless Steel and Brass, Stainess Steel and Bronze, Stainless Steel and Black Tone, Stainless Steel and Ceramic, Stainless Steel and Carbon Fiber, Stainless Steel and Titanium Coating, Stainless Steel, Tungsten Carbide, Titanium, Tantalum, White Gold Rhodium Plated, White Gold Rhodium Plated and Platinum, White Gold Rhodium Plated and Stainless Steel, Yellow Gold, Yellow Gold and Platinum, Yellow Gold and Stainless Steel, Yellow Tone, Yellow Tone and Stainless Steel
case_color: Black, Brown, Red, Rose, White, Yellow, Yellow-White, Blue, Golden, Gray, Green, Multi Colored, Orange, Pink, Purple, Rose-White
strap_color: Black, Brown, Blue, Red, Rose, White, Yellow, Golden, Gray, Green, Multi Colored, Orange, Pink, Purple
strap_secondary_color: Black, Blue, Brown, Cream, Golden, Gray, Green, Orange, Pink, Purple
crystal_material: Glass, Plastic, Sapphire, Synthetics Sapphire
special_functions: Activity tracker, Alarm, Altimeter, Back light, Barometer, Calculator, Calendar, Calories counter, Camera, Chronograph, Compass, Countdown, Distance tracking, Email, GPS, Heart rate monitor, Lap timer, Messages, Multi time zone, Music player, Night light, Pedometer, Phone, Pulse monitor, Sleep monitor, Social media, Solar powered, Stop watch, Voice control, Web search
clasp_type: Butterfly Deployant, Hidden Folding (Crown), Non-Closure, Pin Buckle, Sliding Buckle, Velcro Strap
bezel_type: Compass, Countdown, Count Up, Diamond, Fluted, GMT, Pattern, Plain, Rolex Ring Command, Slide rule, Tachymeter, Ceramic, Numbered
winding_crown: Domed, Triplock, Twinlock
gender: Baby, Gents, Ladies, Unisex
limited_production: Yes, No
watch_size: L, M, S, XL, XS, mini
Text/Numeric Fields: case_diameter, case_thickness_mm, strap_bracelet_width_mm, power_reserve_hour, water_resistance_m, calibre, precision, certification, msrp_price, year_produced, treatment, watch_brand, watch_collection
8. Rules for AI Assistant
Always maintain the strict BC365 schema. Do not invent new fields or valid options.
Preserve the _normalize_to_bc365 strict matching logic.
Ensure firecrawl_proxy.py remains a standalone script executed via subprocess.run.
When writing AL code for Business Central, always use HttpClient.Timeout(600000).
9. Current State & Progress
Jewelry Step 1 & 2 are fully working on Production (Port 8000).
Test Instance is running on Port 8001.
NEXT PHASE: Add category routing to api.py. If category == "watch", use the new Watch Pydantic model, Watch Vision Prompt, and VALID_BC365_WATCH_OPTIONS mapping.
