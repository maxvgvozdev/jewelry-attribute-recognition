# Sample Business Central AL code to call the Jewelry Recognition API

pageextension 50100 CustomerListExtension extends "Customer List"
{
    layout
    {
        addlast(Content)
        {
            group(JewelryRecognition)
            {
                Caption = 'Jewelry Recognition';
                field(JewelryBrand; Rec."No.") { ApplicationArea = All; }
            }
        }
    }
}

codeunit 50100 JewelryRecognitionClient
{
    var
        JewelryApiUrl: Text;
        HttpClient: HttpClient;
        HttpResponse: HttpResponseMessage;
        RequestContent: HttpContent;
        RequestHeaders: HttpHeaders;
        RequestMessage: HttpRequestMessage;

    procedure RecognizeJewelry(Brand: Text; VendorItemNumber: Text; UpcCode: Text; SourceUrl: Text): JsonObject
    var
        Body: JsonObject;
        Token: JsonToken;
    begin
        JewelryApiUrl := 'http://<SERVER>:8000/api/jewelry/recognize';

        Body.Add('brand', Brand);
        Body.Add('vendor_item_number', VendorItemNumber);
        Body.Add('upc_code', UpcCode);
        Body.Add('source_url', SourceUrl);

        RequestContent.WriteFrom(Body.AsToken());
        RequestContent.GetHeaders(RequestHeaders);
        RequestHeaders.Remove('Content-Type');
        RequestHeaders.Add('Content-Type', 'application/json');

        RequestMessage.Method := 'POST';
        RequestMessage.SetRequestUri(Brand, JewelryApiUrl); // corrected below
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
        JsonReader: JsonReader;
        JsonObject: JsonObject;
    begin
        HttpResponse.Content.ReadAs(ResponseText);
        if JsonObject.ReadFrom(ResponseText) then
            exit(JsonObject);
        
        JsonObject.Add('raw', ResponseText);
        exit(JsonObject);
    end;
}
