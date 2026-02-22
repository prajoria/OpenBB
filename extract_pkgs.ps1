$sp = "I:\masterswork\git\OpenBB\.venv\lib\python3.12\site-packages"
$outFile = "I:\masterswork\git\OpenBB\requirements_linux_venv.txt"
$dirs = Get-ChildItem "$sp\*.dist-info" -Directory
$results = @()
foreach ($d in $dirs) {
    $lines = Get-Content "$($d.FullName)\METADATA" -TotalCount 20
    $n = ""
    $v = ""
    foreach ($l in $lines) {
        if ($l -match "^Name: (.+)") { $n = $Matches[1].Trim() }
        if ($l -match "^Version: (.+)") { $v = $Matches[1].Trim() }
    }
    if ($n -and $v) { $results += "$n==$v" }
}
$results | Sort-Object | Set-Content $outFile
Write-Output "Exported $($results.Count) packages to $outFile"
