$ErrorActionPreference = "SilentlyContinue"
$base64 = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes((Get-Content "docs/SOURCES_GOV.md" -Raw)))
$body = @{
    message = "docs: add 政府官网+微信公众号信源清单"
    content = $base64
    branch = "master"
} | ConvertTo-Json -Compress
$body | Out-File -FilePath "body.json" -Encoding UTF8
Write-Host "Body written. Size: $((Get-Content body.json).Length)"
