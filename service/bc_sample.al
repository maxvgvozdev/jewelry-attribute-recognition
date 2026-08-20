codeunit 50100 JewelryRecognitionClient
{
    var
        HttpClient: HttpClient;

    // =========================================================================
    // STEP 2: Item Enrichment (Recognize Jewelry from Web/Images)
    // =========================================================================
    procedure RecognizeJewelry(Brand: Text; VendorItemNumber: Text; UpcCode: Text; SourceUrl: Text; PreFilledAttributes: JsonObject) ResponseJson: JsonObject
    var
        JewelryApiUrl: Label 'http://100.88.93.128:8000/api/jewelry/recognize', Locked = true;
        Body: JsonObject;
        RequestContent: HttpContent;
        RequestHeaders: HttpHeaders;
        RequestMessage: HttpRequestMessage;
        HttpResponse: HttpResponseMessage;
        ErrorResponse: JsonObject;
    begin
        // CRITICAL: Increase timeout to 10 minutes. Vision AI takes much longer than BC's default 100s.
        HttpClient.Timeout(600000);

        Body.Add('brand', Brand);
        Body.Add('vendor_item_number', VendorItemNumber);
        Body.Add('upc_code', UpcCode);
        Body.Add('source_url', SourceUrl);
        
        // Send the attributes parsed from the invoice (Step 1)
        if not PreFilledAttributes.IsEmpty() then
            Body.Add('pre_filled_attributes', PreFilledAttributes);

        RequestContent.WriteFrom(Body.AsToken());
        RequestContent.GetHeaders(RequestHeaders);
        RequestHeaders.Remove('Content-Type');
        RequestHeaders.Add('Content-Type', 'application/json');

        RequestMessage.Method := 'POST';
        RequestMessage.SetRequestUri(JewelryApiUrl); 
        RequestMessage.Content := RequestContent;

        if HttpClient.Send(RequestMessage, HttpResponse) then begin
            if HttpResponse.IsSuccessStatusCode() then begin
                ResponseJson := ParseHttpResponse(HttpResponse);
            end else begin
                ErrorResponse.Add('error', 'HTTP ' + Format(HttpResponse.HttpStatusCode()));
                ErrorResponse.Add('response_text', GetResponseText(HttpResponse));
                ResponseJson := ErrorResponse;
            end;
        end else begin
            ErrorResponse.Add('error', 'Network request failed to reach Python API.');
            ResponseJson := ErrorResponse;
        end;
    end;

    // =========================================================================
    // STEP 1: Invoice Parsing (Upload PDF to Spark AI)
    // =========================================================================
    procedure ParseInvoicePdf(PdfInStream: InStream; FileName: Text) ResponseJson: JsonObject
    var
        InvoiceApiUrl: Label 'http://100.88.93.128:8000/api/invoice/parse', Locked = true;
        RequestContent: HttpContent;
        RequestHeaders: HttpHeaders;
        RequestMessage: HttpRequestMessage;
        HttpResponse: HttpResponseMessage;
        ErrorResponse: JsonObject;
    begin
        // CRITICAL: Increase timeout to 10 minutes. PDF parsing takes a long time.
        HttpClient.Timeout(600000);

        // Write the PDF stream directly into the Request Content
        RequestContent.WriteFrom(PdfInStream);
        
        // Set headers for multipart/form-data file upload
        RequestContent.GetHeaders(RequestHeaders);
        RequestHeaders.Remove('Content-Type');
        RequestHeaders.Add('Content-Type', 'multipart/form-data; boundary=--Boundary_ABC123');

        RequestMessage.Method := 'POST';
        RequestMessage.SetRequestUri(InvoiceApiUrl);
        RequestMessage.Content := RequestContent;

        if HttpClient.Send(RequestMessage, HttpResponse) then begin
            if HttpResponse.IsSuccessStatusCode() then begin
                ResponseJson := ParseHttpResponse(HttpResponse);
            end else begin
                ErrorResponse.Add('error', 'HTTP ' + Format(HttpResponse.HttpStatusCode()));
                ErrorResponse.Add('response_text', GetResponseText(HttpResponse));
                ResponseJson := ErrorResponse;
            end;
        end else begin
            ErrorResponse.Add('error', 'Network request failed to reach Python API.');
            ResponseJson := ErrorResponse;
        end;
    end;

    // =========================================================================
    // Helper Methods
    // =========================================================================
    local procedure ParseHttpResponse(HttpResponse: HttpResponseMessage): JsonObject
    var
        ResponseText: Text;
        ResponseJson: JsonObject;
    begin
        HttpResponse.Content.ReadAs(ResponseText);
        if ResponseJson.ReadFrom(ResponseText) then
            exit(ResponseJson);
        
        // Fallback if the response isn't valid JSON
        ResponseJson.Add('raw', ResponseText);
        exit(ResponseJson);
    end;

    local procedure GetResponseText(HttpResponse: HttpResponseMessage): Text
    var
        ResponseText: Text;
    begin
        HttpResponse.Content.ReadAs(ResponseText);
        exit(ResponseText);
    end;
}