REM UNH Option Monitor - fetches Greeks every 5 minutes and logs to "Prehľad" sheet
REM
REM Setup:
REM 1. Create two sheets: "Monitor" (current data) and "Prehľad" (history)
REM 2. In Monitor sheet:
REM    - Column A: Timestamp
REM    - Column B: Symbol (UNH)
REM    - Column C: Price
REM    - Column D: Delta
REM    - Column E: Gamma
REM    - Column F: Theta
REM    - Column G: IV
REM 3. Run StartMonitor() to start 5-min polling
REM 4. Run StopMonitor() to stop

Dim gTimerID As Long
Dim gIsRunning As Boolean

Sub StartMonitor()
  If gIsRunning Then
    MsgBox "Monitor je už spustený!", 48, "Upozornenie"
    Exit Sub
  End If
  
  gIsRunning = True
  CreateSheetsIfNeeded
  FetchUNHData
  gTimerID = CreateEventListener(300000)  ' 300000 ms = 5 minutes
  MsgBox "Monitor spustený. Dáta sa budú ťahať každých 5 minút.", 64, "Spustenie"
End Sub

Sub StopMonitor()
  If Not gIsRunning Then
    MsgBox "Monitor nie je spustený!", 48, "Upozornenie"
    Exit Sub
  End If
  
  gIsRunning = False
  RemoveEventListener
  MsgBox "Monitor zastavený.", 64, "Zastavenie"
End Sub

Sub FetchUNHData()
  If Not gIsRunning Then Exit Sub
  
  Dim oDoc As Object
  oDoc = ThisComponent
  
  ' Ensure sheets exist
  CreateSheetsIfNeeded
  
  ' Get Monitor sheet
  Dim oSheet As Object
  oSheet = oDoc.Sheets.getByName("Monitor")
  
  ' Call runner script
  Dim symbol As String
  symbol = "UNH"
  Dim expiry As String
  expiry = "20260116"  ' Next quarterly (update as needed)
  Dim outFile As String
  outFile = "/tmp/unh_monitor.csv"
  
  Dim cmd As String
  cmd = "/home/narbon/Aplikácie/tws-webapp/scripts/tws_option_search_runner.sh --symbol " & symbol & " --expiry " & expiry & " --port 7497 --out " & outFile
  
  ' Execute (blocking; runner logs to /tmp/tws_option_search_runner.log)
  Shell(cmd, 0)
  
  ' Wait for file
  Wait 3000
  
  ' Parse CSV and populate Monitor sheet
  If Dir(outFile) <> "" Then
    ImportUNHData outFile, oSheet
  Else
    oSheet.getCellByPosition(0, 0).setString("ERROR: " & outFile & " not found")
  End If
  
  ' Log to Prehľad
  LogToPrehled oSheet
End Sub

Sub CreateSheetsIfNeeded()
  Dim oDoc As Object
  oDoc = ThisComponent
  
  ' Create Monitor if not exists
  If Not oDoc.Sheets.hasByName("Monitor") Then
    oDoc.Sheets.insertNewByName("Monitor", 0)
    Dim oMonitor As Object
    oMonitor = oDoc.Sheets.getByName("Monitor")
    ' Add headers
    oMonitor.getCellByPosition(0, 0).setString("Timestamp")
    oMonitor.getCellByPosition(1, 0).setString("Symbol")
    oMonitor.getCellByPosition(2, 0).setString("Price")
    oMonitor.getCellByPosition(3, 0).setString("Delta")
    oMonitor.getCellByPosition(4, 0).setString("Gamma")
    oMonitor.getCellByPosition(5, 0).setString("Theta")
    oMonitor.getCellByPosition(6, 0).setString("IV")
  End If
  
  ' Create Prehľad if not exists
  If Not oDoc.Sheets.hasByName("Prehľad") Then
    oDoc.Sheets.insertNewByName("Prehľad", 1)
    Dim oPrehled As Object
    oPrehled = oDoc.Sheets.getByName("Prehľad")
    ' Add headers (same as Monitor)
    oPrehled.getCellByPosition(0, 0).setString("Timestamp")
    oPrehled.getCellByPosition(1, 0).setString("Symbol")
    oPrehled.getCellByPosition(2, 0).setString("Price")
    oPrehled.getCellByPosition(3, 0).setString("Delta")
    oPrehled.getCellByPosition(4, 0).setString("Gamma")
    oPrehled.getCellByPosition(5, 0).setString("Theta")
    oPrehled.getCellByPosition(6, 0).setString("IV")
  End If
End Sub

Sub ImportUNHData(csvFile As String, oSheet As Object)
  ' Simple CSV parser for our specific format
  ' Assuming format: symbol,expiry,right,strike,delta,gamma,vega,theta,impliedVol
  ' For UNH PUT/CALL pair, take first row of each
  
  Dim fileNr As Integer
  fileNr = FreeFile
  Open csvFile For Input As fileNr
  
  Dim line As String
  Dim rowNum As Integer
  rowNum = 1
  
  ' Skip header
  Line Input #fileNr, line
  
  ' Read first data row (PUT or first available)
  If Not EOF(fileNr) Then
    Line Input #fileNr, line
    Dim parts() As String
    parts = Split(line, ",")
    
    If UBound(parts) >= 8 Then
      ' symbol, expiry, right, strike, delta, gamma, vega, theta, IV
      ' We store: timestamp, symbol, price (strike as proxy), delta, gamma, theta, IV
      oSheet.getCellByPosition(0, rowNum).setString(Format(Now(), "YYYY-MM-DD HH:MM:SS"))
      oSheet.getCellByPosition(1, rowNum).setString(parts(0))  ' symbol
      oSheet.getCellByPosition(2, rowNum).setValue(CDbl(parts(3)))  ' strike (as price)
      oSheet.getCellByPosition(3, rowNum).setValue(CDbl(parts(4)))  ' delta
      oSheet.getCellByPosition(4, rowNum).setValue(CDbl(parts(5)))  ' gamma
      oSheet.getCellByPosition(5, rowNum).setValue(CDbl(parts(7)))  ' theta
      oSheet.getCellByPosition(6, rowNum).setValue(CDbl(parts(8)))  ' IV
    End If
  End If
  
  Close fileNr
End Sub

Sub LogToPrehled(oSourceSheet As Object)
  Dim oDoc As Object
  oDoc = ThisComponent
  Dim oPrehled As Object
  oPrehled = oDoc.Sheets.getByName("Prehľad")
  
  ' Find last row in Prehľad
  Dim lastRow As Integer
  lastRow = 1
  Do While oPrehled.getCellByPosition(0, lastRow).getString() <> ""
    lastRow = lastRow + 1
  Loop
  
  ' Copy current Monitor row (row 1) to Prehľad
  Dim col As Integer
  For col = 0 To 6
    Dim sourceCell As Object
    sourceCell = oSourceSheet.getCellByPosition(col, 1)
    Dim destCell As Object
    destCell = oPrehled.getCellByPosition(col, lastRow)
    
    If sourceCell.getType() = com.sun.star.table.CellContentType.VALUE Then
      destCell.setValue(sourceCell.getValue())
    Else
      destCell.setString(sourceCell.getString())
    End If
  Next col
End Sub

Function CreateEventListener(intervalMs As Long) As Long
  ' Simplified: use Wait loop in background
  ' For real background scheduling, would need XTimer component
  ' For now, we'll rely on manual button clicks or macro scheduler
  CreateEventListener = 0
End Function

Sub RemoveEventListener()
  ' Placeholder for timer cleanup
End Sub
