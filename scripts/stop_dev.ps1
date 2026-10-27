param()
$ErrorActionPreference = 'Stop'
$projectRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$targets = Get-CimInstance Win32_Process | Where-Object {
    $_.CommandLine -and $_.CommandLine.Contains($projectRoot) -and
    ($_.CommandLine.Contains('-m uvicorn app.main:app') -or
     $_.CommandLine.Contains('-m scripts.process_mock_jobs') -or
     $_.CommandLine.Contains('-m scripts.run_analysis'))
}
foreach ($target in $targets) {
    Stop-Process -Id $target.ProcessId -Force -ErrorAction SilentlyContinue
}
Write-Output ('Stopped project API/worker processes: ' + @($targets).Count)
