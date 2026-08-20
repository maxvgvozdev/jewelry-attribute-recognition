Business Central Integration Manual: Jewelry Attribute Recognition API
1. Overview
This document outlines how to integrate the Jewelry Attribute Recognition API into Microsoft Business Central using AL.

The API operates in a 2-Step Workflow:

Step 1 (Invoice Parsing): BC uploads a vendor invoice PDF. The API uses Spark AI to extract Vendor Info, Line Items, Brand, and basic Jewelry Attributes.
Step 2 (Item Enrichment): BC sends the extracted Item Number, Brand, and the pre-filled attributes from Step 1. The API searches the web, downloads images, uses Vision AI to analyze them, and fills in any missing attributes.
Because both steps involve Vision AI processing, responses can take up to 600 seconds (10 minutes). Direct synchronous calls from the BC UI will crash the user session. This manual uses a background Job Queue architecture to handle this gracefully.

API Endpoints:

Step 1: POST http://<SERVER_IP>:8000/api/invoice/parse
Step 2: POST http://<SERVER_IP>:8000/api/jewelry/recognize
2. Prerequisites
Network Access: The BC Server must be able to reach the Python API server on port 8000.
Error Handling: The API returns standard HTTP status codes:
200 OK: Success.
404 Not Found: Search failed to find the item. (BC should log this or prompt the user for a direct source_url).
500 Internal Server Error: Vision AI, Firecrawl, or network failure.
3. Data Structure: The 31 Attributes Table
Create a dedicated table to hold the exact 31 attributes returned by the API. This keeps the standard Item table clean and groups the jewelry-specific data logically.

al

table 50101 "Jewelry Item Attribute"
{
    Caption = 'Jewelry Item Attribute';
    DataClassification = CustomerContent;
    LookupPageId = "Jewelry Item Attributes List";
    DrillDownPageId = "Jewelry Item Attributes List";

    fields
    {
        field(1; "Item No."; Code[20]) { }
        field(10; "Metal Type"; Text[100]) { }
        field(11; "Metal Color"; Text[100]) { }
        field(12; "Stone Primary Color"; Text[100]) { }
        field(13; "Product Type"; Text[100]) { }
        field(14; "Gender"; Text[100]) { }
        field(15; "Center Stone Type"; Text[100]) { }
        field(16; "Center Stone Shape"; Text[100]) { }
        field(17; "Side Stone 1 Type"; Text[100]) { }
        field(18; "Side Stone 1 Shape"; Text[100]) { }
        field(19; "Side Stone 2 Type"; Text[100]) { }
        field(20; "Side Stone 2 Shape"; Text[100]) { }
        field(21; "Engagement Set Type"; Text[100]) { }
        field(22; "Engagement Ring Type"; Text[100]) { }
        field(23; "Wedding Band Type"; Text[100]) { }
        field(24; "Wedding Band Setting Type"; Text[100]) { }
        field(25; "Wedding Band Stone Continuity"; Text[100]) { }
        field(26; "Fashion Ring Type"; Text[100]) { }
        field(27; "Earring Type"; Text[100]) { }
        field(28; "Necklace Type"; Text[100]) { }
        field(29; "Bracelet Type"; Text[100]) { }
        field(30; "Accessory Type"; Text[100]) { }
        field(31; "Theme"; Text[100]) { }
        field(32; "Occasion"; Text[100]) { }
        field(33; "Jewelry Shape"; Text[100]) { }
        field(34; "Motif"; Text[100]) { }
        field(35; "Finishing Type"; Text[100]) { }
        field(36; "Estate Period"; Text[100]) { }
        field(37; "Holiday Code"; Text[100]) { }
        field(38; "Chain Type"; Text[100]) { }
        field(39; "Clasp Type"; Text[100]) { }
        field(40; "Earring Back"; Text[100]) { }
    }
    
    keys
    {
        key(PK; "Item No.") { Clustered = true; }
    }
}

4. Core Integration Codeunit
This codeunit handles the HTTP requests for both Step 1 (PDF Upload) and Step 2 (Item Enrichment). It safely parses JSON null values and maps all 31 fields.

al

codeunit 50100 "Jewelry AI Mgmt."
{
    var
        APIBaseUrl: Text;

    local procedure GetApiUrl(): Text
    begin
        // Set this via your setup table or hardcoded for testing
        exit('http://<SERVER_IP>:8000');
    end;

    // =========================================================================
    // STEP 1: Parse Invoice PDF
    // =========================================================================
    procedure ParseInvoicePdf(PdfInStream: InStream; FileName: Text) ResponseJson: JsonObject
    var
        Client: HttpClient;
        RequestMessage: HttpRequestMessage;
        Response: HttpResponseMessage;
        RequestContent: HttpContent;
        RequestHeaders: HttpHeaders;
        ErrorResponse: JsonObject;
        MultipartBody: TextBuilder;
        Base64Convert: Codeunit "Base64 Convert";
        PdfBase64: Text;
    begin
        Client.Timeout(600000); // 10 min timeout

        // AL requires manual construction of Multipart Form Data for file uploads
        PdfBase64 := Base64Convert.ToBase64(PdfInStream);
        
        MultipartBody.AppendLine('--Boundary_ABC123');
        MultipartBody.AppendLine('Content-Disposition: form-data; name="file"; filename="' + FileName + '"');
        MultipartBody.AppendLine('Content-Type: application/pdf');
        MultipartBody.AppendLine('');
        MultipartBody.AppendLine(PdfBase64);
        MultipartBody.AppendLine('--Boundary_ABC123--');

        RequestContent.WriteFrom(MultipartBody.ToText());
        RequestContent.GetHeaders(RequestHeaders);
        RequestHeaders.Remove('Content-Type');
        RequestHeaders.Add('Content-Type', 'multipart/form-data; boundary=Boundary_ABC123');

        RequestMessage.Method := 'POST';
        RequestMessage.SetRequestUri(GetApiUrl() + '/api/invoice/parse');
        RequestMessage.Content := RequestContent;

        if Client.Send(RequestMessage, Response) then begin
            if Response.IsSuccessStatusCode() then
                ResponseJson := ParseHttpResponse(Response)
            else begin
                ErrorResponse.Add('error', 'HTTP ' + Format(Response.HttpStatusCode()));
                ErrorResponse.Add('response_text', GetResponseText(Response));
                ResponseJson := ErrorResponse;
            end;
        end else begin
            ErrorResponse.Add('error', 'Network request failed to reach Python API.');
            ResponseJson := ErrorResponse;
        end;
    end;

    // =========================================================================
    // STEP 2: Enrich Item Attributes via Web/Vision AI
    // =========================================================================
    procedure EnrichItemAttributes(ItemNo: Code[20]; Brand: Text; VendorItemNo: Text; UpcCode: Text; SourceUrl: Text; PreFilledAttributes: JsonObject)
    var
        JewelAttr: Record "Jewelry Item Attribute";
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
        RequestBody.Add('brand', Brand);
        RequestBody.Add('vendor_item_number', VendorItemNo);
        RequestBody.Add('upc_code', UpcCode);
        RequestBody.Add('source_url', SourceUrl);
        
        // Pass the attributes extracted from the invoice in Step 1
        if not PreFilledAttributes.IsEmpty() then
            RequestBody.Add('pre_filled_attributes', PreFilledAttributes);

        RequestContent.WriteFrom(Format(RequestBody));
        RequestContent.GetHeaders(RequestHeaders);
        RequestHeaders.Remove('Content-Type');
        RequestHeaders.Add('Content-Type', 'application/json');

        RequestMessage.Method := 'POST';
        RequestMessage.SetRequestUri(GetApiUrl() + '/api/jewelry/recognize');
        RequestMessage.Content := RequestContent;

        // 2. Execute HTTP Call
        if not Client.Send(RequestMessage, Response) then
            Error('Network error connecting to Jewelry AI service.');

        if not Response.IsSuccessStatusCode then begin
            Response.Content().ReadAs(ResponseText);
            Error('API returned error %1: %2', Response.HttpStatusCode, ResponseText);
        end;

        // 3. Parse Response JSON
        Response.Content().ReadAs(ResponseText);
        if not JsonObj.ReadFrom(ResponseText) then
            Error('Invalid JSON returned from API.');

        if not JsonObj.Get('attributes', JToken) then
            Error('API response missing "attributes" object.');
        AttributesObj := JToken.AsObject();

        // 4. Get or Create the Jewelry Attribute record
        if not JewelAttr.Get(ItemNo) then begin
            JewelAttr.Init();
            JewelAttr."Item No." := ItemNo;
            JewelAttr.Insert();
        end;

        // 5. Map ALL 31 JSON fields to BC Table Fields
        JewelAttr.Validate("Metal Type", GetJsonFieldText(AttributesObj, 'metal_type'));
        JewelAttr.Validate("Metal Color", GetJsonFieldText(AttributesObj, 'metal_color'));
        JewelAttr.Validate("Stone Primary Color", GetJsonFieldText(AttributesObj, 'stone_primary_color'));
        JewelAttr.Validate("Product Type", GetJsonFieldText(AttributesObj, 'product_type'));
        JewelAttr.Validate("Gender", GetJsonFieldText(AttributesObj, 'gender'));
        JewelAttr.Validate("Center Stone Type", GetJsonFieldText(AttributesObj, 'center_stone_type'));
        JewelAttr.Validate("Center Stone Shape", GetJsonFieldText(AttributesObj, 'center_stone_shape'));
        JewelAttr.Validate("Side Stone 1 Type", GetJsonFieldText(AttributesObj, 'side_stone_1_type'));
        JewelAttr.Validate("Side Stone 1 Shape", GetJsonFieldText(AttributesObj, 'side_stone_1_shape'));
        JewelAttr.Validate("Side Stone 2 Type", GetJsonFieldText(AttributesObj, 'side_stone_2_type'));
        JewelAttr.Validate("Side Stone 2 Shape", GetJsonFieldText(AttributesObj, 'side_stone_2_shape'));
        JewelAttr.Validate("Engagement Set Type", GetJsonFieldText(AttributesObj, 'engagement_set_type'));
        JewelAttr.Validate("Engagement Ring Type", GetJsonFieldText(AttributesObj, 'engagement_ring_type'));
        JewelAttr.Validate("Wedding Band Type", GetJsonFieldText(AttributesObj, 'wedding_band_type'));
        JewelAttr.Validate("Wedding Band Setting Type", GetJsonFieldText(AttributesObj, 'wedding_band_setting_type'));
        JewelAttr.Validate("Wedding Band Stone Continuity", GetJsonFieldText(AttributesObj, 'wedding_band_stone_continuity'));
        JewelAttr.Validate("Fashion Ring Type", GetJsonFieldText(AttributesObj, 'fashion_ring_type'));
        JewelAttr.Validate("Earring Type", GetJsonFieldText(AttributesObj, 'earring_type'));
        JewelAttr.Validate("Necklace Type", GetJsonFieldText(AttributesObj, 'necklace_type'));
        JewelAttr.Validate("Bracelet Type", GetJsonFieldText(AttributesObj, 'bracelet_type'));
        JewelAttr.Validate("Accessory Type", GetJsonFieldText(AttributesObj, 'accessory_type'));
        JewelAttr.Validate("Theme", GetJsonFieldText(AttributesObj, 'theme'));
        JewelAttr.Validate("Occasion", GetJsonFieldText(AttributesObj, 'occasion'));
        JewelAttr.Validate("Jewelry Shape", GetJsonFieldText(AttributesObj, 'jewelry_shape'));
        JewelAttr.Validate("Motif", GetJsonFieldText(AttributesObj, 'motif'));
        JewelAttr.Validate("Finishing Type", GetJsonFieldText(AttributesObj, 'finishing_type'));
        JewelAttr.Validate("Estate Period", GetJsonFieldText(AttributesObj, 'estate_period'));
        JewelAttr.Validate("Holiday Code", GetJsonFieldText(AttributesObj, 'holiday_code'));
        JewelAttr.Validate("Chain Type", GetJsonFieldText(AttributesObj, 'chain_type'));
        JewelAttr.Validate("Clasp Type", GetJsonFieldText(AttributesObj, 'clasp_type'));
        JewelAttr.Validate("Earring Back", GetJsonFieldText(AttributesObj, 'earring_back'));
        
        JewelAttr.Modify(true);
    end;

    local procedure ParseHttpResponse(Response: HttpResponseMessage): JsonObject
    var
        ResponseText: Text;
        ResponseJson: JsonObject;
    begin
        Response.Content.ReadAs(ResponseText);
        if ResponseJson.ReadFrom(ResponseText) then
            exit(ResponseJson);
        ResponseJson.Add('raw', ResponseText);
        exit(ResponseJson);
    end;

    local procedure GetResponseText(Response: HttpResponseMessage): Text
    var
        ResponseText: Text;
    begin
        Response.Content.ReadAs(ResponseText);
        exit(ResponseText);
    end;

    local procedure GetJsonFieldText(JsonObj: JsonObject; KeyName: Text): Text[100]
    var
        JToken: JsonToken;
    begin
        if JsonObj.Get(KeyName, JToken) then
            if not JToken.IsNull then
                exit(CopyStr(JToken.AsValue().AsText(), 1, MaxStrLen(GetJsonFieldText)));
        exit('');
    end;
}

5. CRITICAL: Asynchronous Background Processing
Do not run either step synchronously from the UI. BC sessions have strict timeouts. Both Step 1 (PDF Parsing) and Step 2 (Web Enrichment) can take minutes.

You must wrap the calls in a Background Job Queue.

al

codeunit 50101 "Jewelry AI Job Queue"
{
    TableNo = "Job Queue Entry";

    trigger OnRun()
    var
        JewelryMgmt: Codeunit "Jewelry AI Mgmt.";
        Item: Record Item;
        // In a real scenario, you'd retrieve the PDF stream and PreFilledAttributes 
        // from a temporary staging table using Rec."Parameter String" as the ID.
    begin
        // Example logic for Step 2:
        if Item.Get(Rec."Parameter String") then begin
            // Fetch pre-filled attributes from staging table...
            // JewelryMgmt.EnrichItemAttributes(Item."No.", Item."Manufacturer Code", Item."Vendor Item No.", Item."GTIN", '', PreFilledAttrs);
        end;
    end;
}

6. UI Integration (Item Card)
Add actions to allow users to trigger the workflow. Typically, a user uploads a PDF (Step 1), reviews the extracted data in BC, and then clicks "Enrich Item" (Step 2).

al

pageextension 50100 "Item Card Ext" extends "Item Card"
{
    actions
    {
        addlast(Processing)
        {
            action(ActionAIEnrich)
            {
                ApplicationArea = All;
                Caption = 'Enrich Jewelry Attributes (Web/Vision)';
                Image = Picture;
                ToolTip = 'Searches the web and uses Vision AI to fill missing jewelry attributes.';

                trigger OnAction()
                var
                    JobQueueEntry: Record "Job Queue Entry";
                    JobQueueMgt: Codeunit "Job Queue - Enqueue";
                begin
                    // Enqueue Step 2
                    JobQueueEntry.Init();
                    JobQueueEntry."Object Type to Run" := JobQueueEntry."Object Type to Run"::Codeunit;
                    JobQueueEntry."Object ID to Run" := CODEUNIT::"Jewelry AI Job Queue";
                    JobQueueEntry."Parameter String" := Rec."No.";
                    JobQueueEntry."Description" := 'Jewelry AI Enrichment for ' + Rec."No.";
                    JobQueueEntry."Maximum No. of Attempts to Run" := 1;
                    JobQueueMgt.EnqueueJobQueueEntry(JobQueueEntry);
                    
                    Message('Item %1 has been queued for Web/Vision AI enrichment.', Rec."No.");
                end;
            }
        }
    }
}

7. Testing from the BC Server
Before testing inside BC, verify network connectivity and API functionality directly from the Business Central server via PowerShell:

powershell

# 1. Test Health
Invoke-RestMethod -Method Get -Uri http://<SERVER_IP>:8000/health

# 2. Test Step 1 (Invoice Parsing - requires multipart form construction)
# (Best tested directly through the API Swagger UI at http://<SERVER_IP>:8000/docs)

# 3. Test Step 2 (Item Enrichment)
Invoke-RestMethod -Method Post -Uri http://<SERVER_IP>:8000/api/jewelry/recognize `
  -ContentType "application/json" `
  -TimeoutSec 600 `
  -Body '{"brand":"John Hardy","vendor_item_number":"254069","upc_code":"8254292540696","source_url":"","pre_filled_attributes":{"metal_type":"STSILVER","metal_color":"White","product_type":"Bracelets","center_stone_type":"Blue Sapphire"}}' | ConvertTo-Json -Depth 10

  8. Developer Checklist
 Create Jewelry AI Setup table and page. Populate the API Endpoint URL (http://<SERVER_IP>:8000).
 Create Jewelry Item Attribute table with the exact 31 fields specified above.
 Create List Pages for the Attribute table and add a FactBox on the Item Card.
 Deploy Jewelry AI Mgmt. codeunit (handles both Step 1 PDF upload and Step 2 JSON enrichment).
 Deploy the Jewelry AI Job Queue codeunit to handle long-running tasks in the background.
 Confirm the BC Server firewall allows outbound HTTP traffic to the Python API server.
 Test via PowerShell from the BC Server first to rule out network issues.
 Test via BC UI and confirm the user session does not freeze (thanks to Job Queues).