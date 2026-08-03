# Business Central Integration Manual: Jewelry Attribute Recognition API

## 1. Overview
This document outlines how to integrate the Jewelry Attribute Recognition API into Microsoft Business Central using AL. 

The API accepts a Brand, Vendor Item Number, and/or UPC, and returns a standardized 31-attribute JSON payload. **Because the API downloads images and processes them via a Vision AI, responses can take up to 600 seconds.** Therefore, direct synchronous calls from the BC UI will crash the user session. This manual uses a background Job Queue architecture to handle this gracefully.

**API Endpoint:** `POST http://20.230.85.3:8000/api/jewelry/recognize`

## 2. Prerequisites
*   **Network Access:** The BC Server must be able to reach the Python API server on port 8000.
*   **Error Handling:** The API returns standard HTTP status codes:
    *   `200 OK`: Success.
    *   `404 Not Found`: Search failed to find the item. (BC should log this or prompt the user for a direct `source_url`).
    *   `500 Internal Server Error`: Vision AI or network failure.

## 3. Data Structure: The 31 Attributes Table
Create a dedicated table to hold the exact 31 attributes returned by the API. This keeps the standard `Item` table clean and groups the jewelry-specific data logically.

```al
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
```

## 4. Core Integration Codeunit
This codeunit handles the HTTP request, parses the JSON safely (handling `null` values without errors), and maps all 31 fields.

```al
codeunit 50100 "Jewelry AI Mgmt."
{
    procedure SyncItemAttributes(ItemNo: Code[20])
    var
        JewelrySetup: Record "Jewelry AI Setup";
        Item: Record Item;
        JewelAttr: Record "Jewelry Item Attribute";
        Client: HttpClient;
        Response: HttpResponseMessage;
        RequestBody: Text;
        ResponseText: Text;
        JsonObj: JsonObject;
        AttributesObj: JsonObject;
        JToken: JsonToken;
    begin
        if not JewelrySetup.Get() then
            Error('Jewelry AI Setup is missing.');
        if not Item.Get(ItemNo) then
            Error('Item %1 does not exist.', ItemNo);

        // 1. Build Request Payload
        JsonObj.Add('brand', Item."Manufacturer Code"); 
        JsonObj.Add('vendor_item_number', Item."Vendor Item No.");
        JsonObj.Add('upc_code', Item."GTIN"); 
        JsonObj.Add('source_url', ''); 
        
        JsonObj.WriteTo(RequestBody);

        // 2. Execute HTTP Call
        // Timeout set to 10 minutes (600,000 ms) as Vision AI processing takes time.
        Client.Timeout(600000); 
        if not Client.Post(JewelrySetup."API Endpoint URL" + '/api/jewelry/recognize', RequestBody, Response) then
            Error('Network error connecting to Jewelry AI service.');

        // 3. Handle HTTP Errors
        if not Response.IsSuccessStatusCode then begin
            Response.Content().ReadAs(ResponseText);
            Error('API returned error %1: %2', Response.HttpStatusCode, ResponseText);
        end;

        // 4. Parse Response JSON
        Response.Content().ReadAs(ResponseText);
        if not JsonObj.ReadFrom(ResponseText) then
            Error('Invalid JSON returned from API.');

        // 5. Extract the "attributes" node
        if not JsonObj.Get('attributes', JToken) then
            Error('API response missing "attributes" object.');
        AttributesObj := JToken.AsObject();

        // 6. Get or Create the Jewelry Attribute record for this Item
        if not JewelAttr.Get(ItemNo) then begin
            JewelAttr.Init();
            JewelAttr."Item No." := ItemNo;
            JewelAttr.Insert();
        end;

        // 7. Map ALL 31 JSON fields to BC Table Fields
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
```

## 5. CRITICAL: Asynchronous Background Processing
**Do not bind `Jewelry AI Mgmt.` directly to a page action.** BC sessions have strict timeouts. The API takes up to 600 seconds. Doing this synchronously will freeze and crash the user's session.

You **must** wrap the call in a Background Job Queue.

```al
codeunit 50101 "Jewelry AI Job Queue"
{
    TableNo = "Job Queue Entry";

    trigger OnRun()
    var
        JewelryMgmt: Codeunit "Jewelry AI Mgmt.";
    begin
        if Rec."Parameter String" = '' then
            Error('Item No. is missing in Job Queue Parameter String.');
            
        JewelryMgmt.SyncItemAttributes(Rec."Parameter String");
    end;
}
```

```al
codeunit 50102 "Jewelry AI Action"
{
    [FunctionBehavior(FunctionBehavior::ConfirmCall)]
    procedure QueueItemForRecognition(ItemNo: Code[20])
    var
        JobQueueEntry: Record "Job Queue Entry";
        JobQueueMgt: Codeunit "Job Queue - Enqueue";
    begin
        JobQueueEntry.Init();
        JobQueueEntry."Object Type to Run" := JobQueueEntry."Object Type to Run"::Codeunit;
        JobQueueEntry."Object ID to Run" := CODEUNIT::"Jewelry AI Job Queue";
        JobQueueEntry."Parameter String" := ItemNo;
        JobQueueEntry."Description" := 'Jewelry AI Recognition for ' + ItemNo;
        JobQueueEntry."Maximum No. of Attempts to Run" := 1;
        
        JobQueueMgt.EnqueueJobQueueEntry(JobQueueEntry);
        
        Message('Item %1 has been queued for AI recognition. Attributes will update in the background shortly.', ItemNo);
    end;
}
```

## 6. UI Integration (Item Card)
Add an action to the Item Card page to allow users to trigger the recognition.

```al
pageextension 50100 "Item Card Ext" extends "Item Card"
{
    actions
    {
        addlast(Processing)
        {
            action(ActionAIRecognize)
            {
                ApplicationArea = All;
                Caption = 'Recognize Jewelry Attributes';
                Image = Picture;
                ToolTip = 'Send item details to the AI service to extract jewelry attributes.';

                trigger OnAction()
                var
                    JewelryAIAction: Codeunit "Jewelry AI Action";
                begin
                    JewelryAIAction.QueueItemForRecognition(Rec."No.");
                end;
            }
        }
    }
}
```
*(Optional)*: Add a FactBox on the Item Card page to display the fields from the `Jewelry Item Attribute` table so users can see the results without navigating away.

## 7. Testing from the BC Server
Before testing inside BC, verify network connectivity and API functionality directly from the Business Central server via PowerShell:

```powershell
# 1. Test Health
Invoke-RestMethod -Method Get -Uri http://20.230.85.3:8000/health

# 2. Test Full Recognition (Notice the 600s timeout flag is critical)
Invoke-RestMethod -Method Post -Uri http://20.230.85.3:8000/api/jewelry/recognize `
  -ContentType "application/json" `
  -TimeoutSec 600 `
  -Body '{"brand":"Cartier","vendor_item_number":"CRN4817000","upc_code":"","source_url":""}' | ConvertTo-Json -Depth 10
```

## 8. Developer Checklist
- [ ] Create `Jewelry AI Setup` table and page. Populate the API Endpoint URL.
- [ ] Create `Jewelry Item Attribute` table with the exact 31 fields specified above.
- [ ] Create List Pages for the Attribute table and add a FactBox on the `Item Card`.
- [ ] Deploy the 3 Codeunits (`Mgmt`, `Job Queue`, `Action`).
- [ ] Add the Action to the `Item Card` page extension.
- [ ] Confirm the BC Server firewall allows outbound HTTP traffic to the Python API server.
- [ ] Test via PowerShell from the BC Server first to rule out network issues.
- [ ] Test via BC UI and confirm the user session does not freeze (thanks to Job Queues).