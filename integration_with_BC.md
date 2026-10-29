Business Central Integration Manual: Jewelry & Watch Attribute Recognition API
1. Overview
This document outlines how to integrate the Jewelry & Watch Attribute Recognition API into Microsoft Business Central using AL.

The API operates in a 2-Step Workflow:

Step 1 (Invoice Parsing): BC uploads a vendor invoice PDF. The API uses Vision AI to extract Vendor Info, Line Items, Category (Jewelry/Watch), and pre-filled attributes.
Step 2 (Item Enrichment): BC sends the extracted Item Number, Brand, Category, and pre-filled attributes from Step 1. The API searches the web, downloads images, uses Vision AI to analyze them, and fills in any missing attributes.
Because both steps involve Vision AI processing, responses can take up to 600 seconds (10 minutes). Direct synchronous calls from the BC UI will crash the user session. This manual uses a background Job Queue architecture to handle this gracefully.

API Endpoints (Dual Instance)
Production: http://<SERVER_IP>:8000
Test Instance: http://<SERVER_IP>:8001 (Use this for all development and testing)
Step 1: POST /api/invoice/parse
Step 2: POST /api/jewelry/recognize
2. Prerequisites
Network Access: The BC Server must be able to reach the Python API server on port 8000 (Production) or 8001 (Test).
Item Category Setup: Ensure your BC Items have a designated category code or manufacturing policy to distinguish between "Jewelry" and "Watch" so the AL code knows which payload to send.
3. Data Structure: The Attribute Tables
The API returns two entirely different sets of attributes depending on the category field. You must create two separate tables in BC to hold this data.

3.1 Jewelry Attribute Table (31 Attributes)
table 50101 "Jewelry Item Attribute"{    Caption = 'Jewelry Item Attribute';    DataClassification = CustomerContent;    LookupPageId = "Jewelry Item Attributes List";    DrillDownPageId = "Jewelry Item Attributes List";    fields    {        field(1; "Item No."; Code[20]) { }        field(10; "Metal Type"; Text[100]) { }        field(11; "Metal Color"; Text[100]) { }        field(12; "Stone Primary Color"; Text[100]) { }        field(13; "Product Type"; Text[100]) { }        field(14; "Gender"; Text[100]) { }        field(15; "Center Stone Type"; Text[100]) { }        field(16; "Center Stone Shape"; Text[100]) { }        field(17; "Side Stone 1 Type"; Text[100]) { }        field(18; "Side Stone 1 Shape"; Text[100]) { }        field(19; "Side Stone 2 Type"; Text[100]) { }        field(20; "Side Stone 2 Shape"; Text[100]) { }        field(21; "Engagement Set Type"; Text[100]) { }        field(22; "Engagement Ring Type"; Text[100]) { }        field(23; "Wedding Band Type"; Text[100]) { }        field(24; "Wedding Band Setting Type"; Text[100]) { }        field(25; "Wedding Band Stone Continuity"; Text[100]) { }        field(26; "Fashion Ring Type"; Text[100]) { }        field(27; "Earring Type"; Text[100]) { }        field(28; "Necklace Type"; Text[100]) { }        field(29; "Bracelet Type"; Text[100]) { }        field(30; "Accessory Type"; Text[100]) { }        field(31; "Theme"; Text[100]) { }        field(32; "Occasion"; Text[100]) { }        field(33; "Jewelry Shape"; Text[100]) { }        field(34; "Motif"; Text[100]) { }        field(35; "Finishing Type"; Text[100]) { }        field(36; "Estate Period"; Text[100]) { }        field(37; "Holiday Code"; Text[100]) { }        field(38; "Chain Type"; Text[100]) { }        field(39; "Clasp Type"; Text[100]) { }        field(40; "Earring Back"; Text[100]) { }    }    keys    {        key(PK; "Item No.") { Clustered = true; }    }}
3.2 Watch Attribute Table (40+ Attributes)
al

table 50102 "Watch Item Attribute"
{
    Caption = 'Watch Item Attribute';
    DataClassification = CustomerContent;
    LookupPageId = "Watch Item Attributes List";
    DrillDownPageId = "Watch Item Attributes List";

    fields
    {
        field(1; "Item No."; Code[20]) { }
        field(10; "Functions Complications"; Text[100]) { }
        field(11; "Watch Style"; Text[100]) { }
        field(12; "Movement Type"; Text[100]) { }
        field(13; "Display Type"; Text[100]) { }
        field(14; "Case Diameter"; Text[50]) { }
        field(15; "Case Thickness mm"; Text[50]) { }
        field(16; "Case Shape"; Text[100]) { }
        field(17; "Dial Color"; Text[100]) { }
        field(18; "Case Back"; Text[100]) { }
        field(19; "Dial Motif"; Text[100]) { }
        field(20; "Watch Display Number Type"; Text[100]) { }
        field(21; "Dial Embellishment"; Text[100]) { }
        field(22; "Case Material"; Text[100]) { }
        field(23; "Strap Bracelet Type"; Text[100]) { }
        field(24; "Strap Bracelet Material"; Text[100]) { }
        field(25; "Case Color"; Text[100]) { }
        field(26; "Strap Color"; Text[100]) { }
        field(27; "Strap Secondary Color"; Text[100]) { }
        field(28; "Strap Bracelet Width mm"; Text[50]) { }
        field(29; "Crystal Material"; Text[100]) { }
        field(30; "Special Functions"; Text[100]) { }
        field(31; "Power Reserve Hour"; Text[50]) { }
        field(32; "Water Resistance m"; Text[50]) { }
        field(33; "Clasp Type"; Text[100]) { }
        field(34; "Watch Brand"; Text[100]) { }
        field(35; "Watch Collection"; Text[100]) { }
        field(36; "Bezel Type"; Text[100]) { }
        field(37; "Winding Crown"; Text[100]) { }
        field(38; "Calibre"; Text[100]) { }
        field(39; "Precision"; Text[100]) { }
        field(40; "Certification"; Text[100]) { }
        field(41; "Gender"; Text[100]) { }
        field(42; "MSRP Price"; Text[50]) { }
        field(43; "Year Produced"; Text[20]) { }
        field(44; "Limited Production"; Text[10]) { }
        field(45; "Watch Size"; Text[10]) { }
        field(46; "Treatment"; Text[100]) { }
    }
    keys
    {
        key(PK; "Item No.") { Clustered = true; }
    }
}
4. Core Integration Codeunit
This codeunit handles Step 2. It now accepts a Category parameter, routes the HTTP request accordingly, and maps either the 31 Jewelry fields or the 40+ Watch fields.

al

codeunit 50100 "Jewelry & Watch AI Mgmt."
{
    var
        APIBaseUrl: Text;

    local procedure GetApiUrl(): Text
    begin
        // Point to 8001 for Test, 8000 for Prod
        exit('http://<SERVER_IP>:8001'); 
    end;

    // =========================================================================
    // STEP 2: Enrich Item Attributes via Web/Vision AI
    // =========================================================================
    procedure EnrichItemAttributes(ItemNo: Code[20]; Category: Text; Brand: Text; VendorItemNo: Text; UpcCode: Text; SourceUrl: Text; PreFilledAttributes: JsonObject)
    var
        Client: HttpClient;
        Response: HttpResponseMessage;
        RequestBody: JsonObject;
        RequestContent: HttpContent;
        RequestHeaders: HttpHeaders;
        RequestMessage: HttpRequestMessage;
        ResponseText: Text;
        JsonObj: JsonObject;
        AttributesObj: JsonObject;
        JToken: JsonToken;
    begin
        Client.Timeout(600000); // 10 min timeout

        // 1. Build Request Payload
        RequestBody.Add('category', Category);
        RequestBody.Add('brand', Brand);
        RequestBody.Add('vendor_item_number', VendorItemNo);
        RequestBody.Add('upc_code', UpcCode);
        RequestBody.Add('source_url', SourceUrl);
        
        if not PreFilledAttributes.IsEmpty() then
            RequestBody.Add('pre_filled_attributes', PreFilledAttributes);

        RequestContent.WriteFrom(Format(RequestBody));
        RequestContent.GetHeaders(RequestHeaders);
        RequestHeaders.Remove('Content-Type');
        RequestHeaders.Add('Content-Type', 'application/json');

        RequestMessage.Method := 'POST';
}
5. CRITICAL: Asynchronous Background Processing
Do not run either step synchronously from the UI. BC sessions have strict timeouts. You must wrap the calls in a Background Job Queue.

al

codeunit 50101 "Jewelry AI Job Queue"
{
    TableNo = "Job Queue Entry";

    trigger OnRun()
    var
        JewelryMgmt: Codeunit "Jewelry & Watch AI Mgmt.";
        Item: Record Item;
        PreFilledAttrs: JsonObject;
        CategoryTxt: Text;
    begin
        // In a real scenario, you'd retrieve the PDF stream and PreFilledAttributes 
        // from a temporary staging table using Rec."Parameter String" as the ID.
        if Item.Get(Rec."Parameter String") then begin
            
            // Determine Category based on BC Item data (e.g., Item Category Code)
            if Item."Item Category Code" = 'WATCH' then
                CategoryTxt := 'watch'
            else
                CategoryTxt := 'jewelry';

            // Fetch pre-filled attributes from staging table...
            // PreFilledAttrs.Add('metal_type', 'STSILVER');
            
            JewelryMgmt.EnrichItemAttributes(Item."No.", CategoryTxt, Item."Manufacturer Code", Item."Vendor Item No.", Item."GTIN", '', PreFilledAttrs);
        end;
    end;
}
6. Testing from the BC Server
Before testing inside BC, verify network connectivity and API functionality directly from the Business Central server via PowerShell.

Test Watch Enrichment (Step 2):

powershell

Invoke-RestMethod -Method Post -Uri http://<SERVER_IP>:8001/api/jewelry/recognize `
  -ContentType "application/json" `
  -TimeoutSec 600 `
  -Body '{
    "category": "watch",
    "brand": "Rolex",
    "vendor_item_number": "126610LN",
    "upc_code": "",
    "source_url": "",
    "pre_filled_attributes": {
      "gender": "Gents",
      "watch_style": "Sport"
    }
  }' | ConvertTo-Json -Depth 10
7. Developer Checklist
 Create Jewelry Item Attribute table (31 fields).
 Create Watch Item Attribute table (40+ fields).
 Create List Pages for both Attribute tables and add FactBoxes to the Item Card (conditionally visible based on Item Category).
 Deploy Jewelry & Watch AI Mgmt. codeunit (handles category routing and maps the 71 combined fields).
 Deploy the Jewelry AI Job Queue codeunit to handle long-running tasks in the background.
 Confirm the BC Server firewall allows outbound HTTP traffic to the Python API server (Port 8000 for Prod, 8001 for Test).
 Test via PowerShell from the BC Server first to rule out network issues.
 Test via BC UI and confirm the user session does not freeze (thanks to Job Queues).


Deployment network update (2026-10-29)
The working BC implementation is maintained separately; AL snippets here are examples, not the deployed integration. API request/response contracts are unchanged by the VPN migration. On the future company server, BC and API will be colocated: use http://127.0.0.1:8000 (test: 8001) only if calls execute in the same host network. Remote or containerized BC requires separately verified addressing and firewall rules. API -> Spark uses http://10.77.0.2:11434 inside the administrator-managed encrypted VPN, replacing Tailscale. See service/ARCHITECTURE_AND_DEPLOYMENT.md for the migration and validation sequence.


## Context-aware product discovery (proposed, 2026-10-29)

Step 2 now passes existing pre_filled_attributes to product search and verification. The non-null product type, stone, stone color, watch material/collection/brand and recognized metal code are search qualifiers; arbitrary attribute names are not concatenated into queries. Legacy category values such as Bracelets remain accepted and are used as a product-type qualifier.

New optional request fields: manufacturer_item_number (Comm. Ref./MPN, separate from vendor_item_number), description (original invoice or BC product description). Step 1 line_items now preserve manufacturer_item_number, upc_code and category alongside sku, sku_alternate and description. BC must explicitly map these into Step 2; the API cannot access BC records or a previous request on its own. Older clients benefit from their existing pre_filled_attributes without adding fields.

Example (verify the full wrapped manufacturer reference against the original invoice before use):

```json
{
  "category": "jewelry",
  "brand": "John Hardy",
  "vendor_item_number": "254069",
  "manufacturer_item_number": "BUS9909044BSPXU2XL",
  "upc_code": "825429254069",
  "description": "Icon Silver 6.5mm Small Bracelet with Blue Sapphire with Pusher Clasp, Size U2XL",
  "pre_filled_attributes": {
    "metal_type": "STSILVER",
    "product_type": "Bracelets",
    "center_stone_type": "Blue Sapphire"
  }
}
```

Search tries multiple quoted identifier queries, enriched with context, and checks up to five candidate pages within a 420-second subprocess budget (API wrapper: 450 seconds). Acceptance requires a matching extracted SKU/MPN/UPC corroborated by raw page markdown and the supplied brand in that markdown. If a manufacturer reference is provided, require that reference or UPC rather than vendor number alone. Product type, silver-vs-karat-gold, selected gemstone and pusher/lobster clasp contradictions are rejected. This is an initial conservative rule set, not a general semantic matcher; some true matches will be rejected when page content lacks identifiers or brand. A supplied source_url goes through the same checks and is insufficient on its own without an identifier. Never silently fall back to the first search result or an invented brand URL.

No confirmed page returns HTTP 404 with rejected_candidates; a discovery process failure returns 502. BC must handle these without populating guessed attributes. No model calls or image downloads are made for unconfirmed products. Unknown/missing facts are not evidence of a contradiction. Image selection avoids combining multi-variant galleries, but still needs real-product QA. evidence.text contains extracted page text only, not concatenated Vision output. Confidence is capped at medium for successful image enrichment; image presence is not identity proof. cross_confirmed requires two distinct supplied identifier values.

Attribute merge order: explicit BC prefill, invoice description, confirmed page text, then Vision fills remaining values. Explicit prefill is reapplied after watch heuristics; final values are normalized. This does not implement a full field-level provenance/conflict engine or eliminate all legacy heuristic limitations.

Validation: run python -m unittest discover -s tests -v from repository root. Real Firecrawl, model and BC integration tests must be performed on port 8001 before production deployment. Test the reported BU98941 mismatch, a known exact match, a no-match case and the full Step 1 -> BC -> Step 2 mapping. More queries/scrapes increase latency; existing 600-second BC timeout may still be exceeded when Vision calls are included.
