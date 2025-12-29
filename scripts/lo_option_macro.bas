REM LibreOffice Basic macro to run the option search script and import CSV into Calc
Sub ImportOptionsFromScript
  Dim symbol As String
  Dim expiry As String
  Dim target As String
  Dim tol As String
  symbol = InputBox("Symbol (e.g. UNH)", "Option Search", "UNH")
  If symbol = "" Then Exit Sub
  expiry = InputBox("Expiry (YYYYMMDD)", "Option Search", "20260116")
  If expiry = "" Then Exit Sub
  target = InputBox("Target delta (e.g. 0.1 or -0.1)", "Option Search", "0.1")
  If target = "" Then Exit Sub
  tol = InputBox("Tolerance (default 0.02)", "Option Search", "0.02")

  Dim outFile As String
  outFile = "/tmp/options_results.csv"

  Dim cmd As String
  cmd = "/home/narbon/Aplikácie/tws-webapp/scripts/tws_option_search_runner.sh --symbol " & symbol & " --expiry " & expiry & " --target " & target & " --tol " & tol & " --out " & outFile

  ' Run the external script (non-blocking shell might return immediately; use synchronous Shell)
  Shell(cmd, 0)

  ' Wait a few seconds for the file to be generated
  Wait 5000

  ' Check file exists
  If Dir(outFile) = "" Then
    Msgbox "CSV not found: " & outFile, 16, "Import failed"
    Exit Sub
  End If

  ' Open the CSV into the current sheet
  Dim oDoc As Object
  oDoc = ThisComponent
  Dim args(0) As new com.sun.star.beans.PropertyValue
  args(0).Name = "FilterName"
  args(0).Value = "Text - txt - csv (StarCalc)"
  oDoc.Sheets(0).Link("file:///" & outFile, "", 0)
  Msgbox "Imported results into sheet 0: " & outFile, 64, "Import complete"
End Sub
