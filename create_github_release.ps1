# Script to create GitHub Release v4.0.0
# Usage: .\create_github_release.ps1 -GitHubToken "your_github_token"

param(
    [Parameter(Mandatory=$true)]
    [string]$GitHubToken
)

$repo = "ngoviet/lumentreeHA"
$tag = "v4.0.0"
$releaseName = "v4.0.0"
$releaseNotes = Get-Content "RELEASE_NOTES_v4.0.0.md" -Raw

# Convert release notes to JSON format (escape newlines and quotes)
$releaseNotesJson = $releaseNotes -replace "`"", "\`"" -replace "`r`n", "\n" -replace "`n", "\n"

$body = @{
    tag_name = $tag
    name = $releaseName
    body = $releaseNotes
    draft = $false
    prerelease = $false
} | ConvertTo-Json

$headers = @{
    "Authorization" = "token $GitHubToken"
    "Accept" = "application/vnd.github.v3+json"
}

$uri = "https://api.github.com/repos/$repo/releases"

try {
    Write-Host "Creating GitHub Release v4.0.0..."
    $response = Invoke-RestMethod -Uri $uri -Method Post -Headers $headers -Body $body -ContentType "application/json"
    Write-Host "✓ Release created successfully!" -ForegroundColor Green
    Write-Host "Release URL: $($response.html_url)" -ForegroundColor Cyan
} catch {
    Write-Host "✗ Error creating release:" -ForegroundColor Red
    Write-Host $_.Exception.Message -ForegroundColor Red
    if ($_.ErrorDetails.Message) {
        Write-Host $_.ErrorDetails.Message -ForegroundColor Red
    }
    exit 1
}

