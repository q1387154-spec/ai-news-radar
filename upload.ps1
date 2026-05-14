$ErrorActionPreference = "SilentlyContinue"
$token = [System.IO.File]::ReadAllText("$env:USERPROFILE\.config\gh\hosts.yml") -replace '(?s).*?github\.com:\s*\n\s*token:\s*(\S+).*','$1'

$base64 = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes((Get-Content "docs/SOURCES_GOV.md" -Raw)))

$body = @{
    message = "docs: add 政府官网+微信公众号信源清单"
    content = $base64
    branch = "master"
} | ConvertTo-Json -Compress

$url = "https://api.github.com/repos/q1387154-spec/ai-news-radar/contents/docs/SOURCES_GOV.md"
$headers = @{ Authorization = "Bearer $token" }
$resp = Invoke-RestMethod $url -Method PUT -Headers $headers -Body $body
$resp | ConvertTo-Json -Depth 5
