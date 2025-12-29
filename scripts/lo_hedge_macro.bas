REM  *****  BASIC  *****
REM LibreOffice Calc Macro - Hedge Spread Finder (List 2 - "Vyhľadávač")
REM
REM Usage:
REM   1. User fills inputs: Symbol, Short Expiry, Short Type, Delta Target, Long Expiry, Long Type
REM   2. Click "Nájsť Hedge" button → runs tws_hedge_finder_runner.sh
REM   3. Wait for JSON result → parse and display in cells
REM   4. Click "SEND TO TWS" button → submit spread order to Paper TWS

Sub HedgeFinder_FindSpread()
    Dim oDoc As Object
    Dim oSheet As Object
    Dim symbol As String, expiry_short As String, type_short As String
    Dim delta_target As String, expiry_long As String, type_long As String
    Dim cmd As String, outFile As String, jsonText As String
    Dim shortStrike As String, shortDelta As String, shortBid As String, shortAsk As String
    Dim longStrike As String, longDelta As String, longBid As String, longAsk As String
    Dim netDelta As String, maxProfit As String, maxLoss As String, breakeven As String
    Dim success As String
    
    oDoc = ThisComponent
    oSheet = oDoc.Sheets.getByName("List2_Vyhlad")  ' Sheet name: "List2_Vyhlad"
    
    ' Read inputs from cells (adjust cell references as needed)
    ' Assume: B2=Symbol, B3=Short Expiry, B4=Short Type, B5=Delta Target
    '         B6=Long Expiry, B7=Long Type
    symbol = Trim(oSheet.getCellByPosition(1, 1).getString())  ' B2
    expiry_short = Trim(oSheet.getCellByPosition(1, 2).getString())  ' B3
    type_short = Trim(oSheet.getCellByPosition(1, 3).getString())  ' B4
    delta_target = Trim(oSheet.getCellByPosition(1, 4).getString())  ' B5
    expiry_long = Trim(oSheet.getCellByPosition(1, 5).getString())  ' B6
    type_long = Trim(oSheet.getCellByPosition(1, 6).getString())  ' B7
    
    ' Validate inputs
    If Len(symbol) = 0 Or Len(expiry_short) = 0 Or Len(type_short) = 0 Or _
       Len(delta_target) = 0 Or Len(expiry_long) = 0 Or Len(type_long) = 0 Then
        MsgBox "Vyplň všetky polia: Symbol, Short Expiry (YYYYMMDD), Type (C/P), Delta, Long Expiry, Type", 48, "Chýbajúce vstupy"
        Exit Sub
    End If
    
    ' Construct command
    outFile = "/tmp/hedge_result.json"
    cmd = "/home/narbon/Aplikácie/tws-webapp/scripts/tws_hedge_finder_runner.sh" & _
          " --symbol " & symbol & _
          " --expiry-short " & expiry_short & _
          " --type-short " & type_short & _
          " --delta-target " & delta_target & _
          " --expiry-long " & expiry_long & _
          " --type-long " & type_long & _
          " --port 7497" & _
          " --out " & outFile
    
    ' Show status
    oSheet.getCellByPosition(1, 8).setString("Hľadám hedge...")  ' B9 status
    
    ' Run command
    Shell(cmd, 0)
    
    ' Wait for result (10 seconds max)
    Dim i As Integer
    For i = 1 To 20
        Wait 500
        If Dir(outFile) <> "" Then
            Exit For
        End If
    Next i
    
    ' Check if file exists
    If Dir(outFile) = "" Then
        oSheet.getCellByPosition(1, 8).setString("CHYBA: JSON súbor sa nevytvoril")
        MsgBox "Hedge finder nevrátil výsledok. Skontroluj log: /tmp/tws_hedge_finder_runner.log", 16, "Chyba"
        Exit Sub
    End If
    
    ' Read JSON file (Basic doesn't have native JSON parser, so we'll parse manually)
    Dim fileNum As Integer
    fileNum = FreeFile
    Open outFile For Input As #fileNum
    jsonText = ""
    While Not EOF(fileNum)
        Line Input #fileNum, lineText
        jsonText = jsonText & lineText
    Wend
    Close #fileNum
    
    ' Parse JSON (simple string extraction - not robust but works for our structure)
    ' Expected: {"success": true/false, "shortLeg": {...}, "longLeg": {...}, "stats": {...}}
    success = ExtractJSONValue(jsonText, "success")
    
    If success <> "true" Then
        Dim errorMsg As String
        errorMsg = ExtractJSONValue(jsonText, "error")
        oSheet.getCellByPosition(1, 8).setString("CHYBA: " & errorMsg)
        MsgBox "Hedge finder error: " & errorMsg, 16, "Chyba"
        Exit Sub
    End If
    
    ' Extract short leg data
    shortStrike = ExtractNestedValue(jsonText, "shortLeg", "strike")
    shortDelta = ExtractNestedValue(jsonText, "shortLeg", "delta")
    shortBid = ExtractNestedValue(jsonText, "shortLeg", "bid")
    shortAsk = ExtractNestedValue(jsonText, "shortLeg", "ask")
    
    ' Extract long leg data
    longStrike = ExtractNestedValue(jsonText, "longLeg", "strike")
    longDelta = ExtractNestedValue(jsonText, "longLeg", "delta")
    longBid = ExtractNestedValue(jsonText, "longLeg", "bid")
    longAsk = ExtractNestedValue(jsonText, "longLeg", "ask")
    
    ' Extract stats
    netDelta = ExtractNestedValue(jsonText, "stats", "netDelta")
    maxProfit = ExtractNestedValue(jsonText, "stats", "maxProfit")
    maxLoss = ExtractNestedValue(jsonText, "stats", "maxLoss")
    breakeven = ExtractNestedValue(jsonText, "stats", "breakeven")
    
    ' Display results in cells (adjust positions as needed)
    ' Short Leg: D2-D5, Long Leg: D6-D9, Stats: D10-D13
    oSheet.getCellByPosition(3, 1).setString("SHORT LEG")  ' D2
    oSheet.getCellByPosition(3, 2).setString("Strike: " & shortStrike)  ' D3
    oSheet.getCellByPosition(3, 3).setString("Delta: " & shortDelta)  ' D4
    oSheet.getCellByPosition(3, 4).setString("Bid/Ask: " & shortBid & "/" & shortAsk)  ' D5
    
    oSheet.getCellByPosition(3, 5).setString("LONG LEG")  ' D6
    oSheet.getCellByPosition(3, 6).setString("Strike: " & longStrike)  ' D7
    oSheet.getCellByPosition(3, 7).setString("Delta: " & longDelta)  ' D8
    oSheet.getCellByPosition(3, 8).setString("Bid/Ask: " & longBid & "/" & longAsk)  ' D9
    
    oSheet.getCellByPosition(3, 9).setString("STATS")  ' D10
    oSheet.getCellByPosition(3, 10).setString("Net Delta: " & netDelta)  ' D11
    oSheet.getCellByPosition(3, 11).setString("Max Profit: $" & maxProfit)  ' D12
    oSheet.getCellByPosition(3, 12).setString("Max Loss: $" & maxLoss)  ' D13
    oSheet.getCellByPosition(3, 13).setString("Breakeven: " & breakeven)  ' D14
    
    oSheet.getCellByPosition(1, 8).setString("OK - Hedge nájdený!")  ' B9 status
    MsgBox "Hedge spread nájdený! Short: " & shortStrike & " (" & shortDelta & ") / Long: " & longStrike & " (" & longDelta & ")", 64, "Úspech"
End Sub


Sub HedgeFinder_SendToTWS()
    ' TODO: Implement order submission to Paper TWS
    ' This will call a new Python script (tws_order_submitter.py) to create and submit spread orders
    MsgBox "SEND TO TWS - zatiaľ neimplementované. Bude volať tws_order_submitter.py", 64, "Info"
End Sub


Function ExtractJSONValue(jsonText As String, key As String) As String
    ' Simple JSON value extractor: finds "key": value or "key": "value"
    Dim pattern As String, startPos As Integer, endPos As Integer
    Dim valueStr As String
    
    pattern = Chr(34) & key & Chr(34) & ":"  ' "key":
    startPos = InStr(jsonText, pattern)
    If startPos = 0 Then
        ExtractJSONValue = ""
        Exit Function
    End If
    
    startPos = startPos + Len(pattern)
    ' Skip whitespace
    While Mid(jsonText, startPos, 1) = " " Or Mid(jsonText, startPos, 1) = Chr(9)
        startPos = startPos + 1
    Wend
    
    ' Check if value is string (starts with ")
    If Mid(jsonText, startPos, 1) = Chr(34) Then
        startPos = startPos + 1
        endPos = InStr(startPos, jsonText, Chr(34))
        valueStr = Mid(jsonText, startPos, endPos - startPos)
    Else
        ' Numeric or boolean value (ends with comma, } or ])
        endPos = startPos
        While endPos <= Len(jsonText)
            Dim ch As String
            ch = Mid(jsonText, endPos, 1)
            If ch = "," Or ch = "}" Or ch = "]" Or ch = " " Then
                Exit While
            End If
            endPos = endPos + 1
        Wend
        valueStr = Trim(Mid(jsonText, startPos, endPos - startPos))
    End If
    
    ExtractJSONValue = valueStr
End Function


Function ExtractNestedValue(jsonText As String, parentKey As String, childKey As String) As String
    ' Extract value from nested JSON: {"parentKey": {"childKey": value}}
    Dim pattern As String, startPos As Integer, endPos As Integer
    Dim parentBlock As String
    
    ' Find parent block
    pattern = Chr(34) & parentKey & Chr(34) & ":"
    startPos = InStr(jsonText, pattern)
    If startPos = 0 Then
        ExtractNestedValue = ""
        Exit Function
    End If
    
    ' Find opening brace of parent object
    startPos = InStr(startPos, jsonText, "{")
    If startPos = 0 Then
        ExtractNestedValue = ""
        Exit Function
    End If
    
    ' Find closing brace (simple approach - assumes no nested objects)
    Dim braceCount As Integer
    braceCount = 1
    endPos = startPos + 1
    While endPos <= Len(jsonText) And braceCount > 0
        If Mid(jsonText, endPos, 1) = "{" Then
            braceCount = braceCount + 1
        ElseIf Mid(jsonText, endPos, 1) = "}" Then
            braceCount = braceCount - 1
        End If
        endPos = endPos + 1
    Wend
    
    parentBlock = Mid(jsonText, startPos, endPos - startPos)
    
    ' Extract child value from parent block
    ExtractNestedValue = ExtractJSONValue(parentBlock, childKey)
End Function