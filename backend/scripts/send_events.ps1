# Windows PowerShell equivalent of send_events.sh
$api = if ($env:API) { $env:API } else { "http://127.0.0.1:3000" }
Set-Location (Join-Path $PSScriptRoot "..")
$tests = @(
  @{ File = "ready.json";         Expected = "Ready for review" },
  @{ File = "needs_changes.json"; Expected = "Needs changes" },
  @{ File = "low_value.json";     Expected = "Low-value or unclear" }
)
foreach ($t in $tests) {
  Write-Host "=== $($t.File)  (expected: $($t.Expected))"
  Invoke-RestMethod -Method Post -Uri "$api/github-webhook" `
    -ContentType "application/json" -Headers @{ "X-GitHub-Event" = "pull_request" } `
    -InFile "events/$($t.File)" | ConvertTo-Json
}
Write-Host "=== GET /prs"
Invoke-RestMethod "$api/prs" | ConvertTo-Json -Depth 6
