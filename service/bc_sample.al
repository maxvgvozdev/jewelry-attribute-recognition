codeunit 50100 JewelryRecognitionClient
{
    var
        JewelryApiUrl: Text;
        HttpClient: HttpClient;
        HttpResponse: HttpResponseMessage;
        RequestContent: HttpContent;
        RequestHeaders: HttpHeaders;
        RequestMessage: HttpRequestMessage;

    // Added PreFilledAttributes parameter
    procedure RecognizeJewelry(Brand: Text; VendorItemNumber: Text; UpcCode: Text; SourceUrl: Text; PreFilledAttributes: JsonObject): JsonObject
    var
        Body: JsonObject;
    begin
        JewelryApiUrl := 'http://<SERVER>:8000/api/jewelry/recognize';

        Body.Add('brand', Brand);
        Body.Add('vendor_item_number', VendorItemNumber);
        Body.Add('upc_code', UpcCode);
        Body.Add('source_url', SourceUrl);
        
        // CRITICAL: Send the attributes parsed from the invoice
        if not PreFilledAttributes.IsEmpty() then
            Body.Add('pre_filled_attributes', PreFilledAttributes);

        RequestContent.WriteFrom(Body.AsToken());
        RequestContent.GetHeaders(RequestHeaders);
        RequestHeaders.Remove('Content-Type');
        RequestHeaders.Add('Content-Type', 'application/json');

        RequestMessage.Method := 'POST';
        // FIX: SetRequestUri takes exactly ONE parameter
        RequestMessage.SetRequestUri(JewelryApiUrl); 
        RequestMessage.Content := RequestContent;

        if HttpClient.Send(RequestMessage, HttpResponse) then begin
            if HttpResponse.IsSuccessStatusCode() then begin
                exit(ParseResponse(HttpResponse));
            end else begin
                Body.Add('error', 'HTTP ' + Format(HttpResponse.HttpStatusCode()));
                exit(Body);
            end;
        end else begin
            Body.Add('error', 'Request failed');
            exit(Body);
        end;
    end;

    local procedure ParseResponse(HttpResponse: HttpResponseMessage): JsonObject
    var
        ResponseText: Text;
        JsonObject: JsonObject;
    begin
        HttpResponse.Content.ReadAs(ResponseText);
        if JsonObject.ReadFrom(ResponseText) then
            exit(JsonObject);
        
        JsonObject.Add('raw', ResponseText);
        exit(JsonObject);
    end;
}