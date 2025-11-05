# Script to create GitHub Release v4.0.0
# Cần GitHub Personal Access Token với quyền 'repo'

param(
    [Parameter(Mandatory=$false)]
    [string]$Token
)

$repo = "ngoviet/lumentreeHA"
$tag = "v4.0.0"
$releaseName = "v4.0.0"

# Đọc release notes
$releaseNotesPath = Join-Path $PSScriptRoot "RELEASE_NOTES_v4.0.0.md"
if (-not (Test-Path $releaseNotesPath)) {
    Write-Host "Không tìm thấy file RELEASE_NOTES_v4.0.0.md" -ForegroundColor Red
    exit 1
}

$releaseNotes = Get-Content $releaseNotesPath -Raw -Encoding UTF8

# Nếu không có token, hướng dẫn người dùng
if ([string]::IsNullOrEmpty($Token)) {
    Write-Host "=== HƯỚNG DẪN TẠO GITHUB RELEASE ===" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "Cách 1: Tạo thủ công (NHANH NHẤT):" -ForegroundColor Cyan
    Write-Host "1. Truy cập: https://github.com/$repo/releases/new" -ForegroundColor White
    Write-Host "2. Chọn tag: $tag" -ForegroundColor White
    Write-Host "3. Title: $releaseName" -ForegroundColor White
    Write-Host "4. Copy nội dung từ file RELEASE_NOTES_v4.0.0.md vào Description" -ForegroundColor White
    Write-Host "5. Click 'Publish release'" -ForegroundColor White
    Write-Host ""
    Write-Host "Cách 2: Dùng script với token:" -ForegroundColor Cyan
    Write-Host "1. Lấy token: https://github.com/settings/tokens" -ForegroundColor White
    Write-Host "2. Tạo token mới với quyền 'repo'" -ForegroundColor White
    Write-Host "3. Chạy: .\create_release.ps1 -Token 'your_token_here'" -ForegroundColor White
    exit 0
}

# Tạo release với token
$body = @{
    tag_name = $tag
    name = $releaseName
    body = $releaseNotes
    draft = $false
    prerelease = $false
} | ConvertTo-Json -Depth 10

$headers = @{
    "Authorization" = "Bearer $Token"
    "Accept" = "application/vnd.github.v3+json"
    "User-Agent" = "PowerShell"
}

$uri = "https://api.github.com/repos/$repo/releases"

try {
    Write-Host "Đang tạo GitHub Release $releaseName..." -ForegroundColor Yellow
    $response = Invoke-RestMethod -Uri $uri -Method Post -Headers $headers -Body $body -ContentType "application/json; charset=utf-8"
    Write-Host "✓ Release đã được tạo thành công!" -ForegroundColor Green
    Write-Host "URL: $($response.html_url)" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "HACS sẽ tự động nhận version mới sau vài phút." -ForegroundColor Green
    Write-Host "Hoặc refresh HACS repository để cập nhật ngay." -ForegroundColor Green
} catch {
    Write-Host "✗ Lỗi khi tạo release:" -ForegroundColor Red
    Write-Host $_.Exception.Message -ForegroundColor Red
    if ($_.ErrorDetails.Message) {
        $errorDetails = $_.ErrorDetails.Message | ConvertFrom-Json -ErrorAction SilentlyContinue
        if ($errorDetails) {
            Write-Host "Chi tiết: $($errorDetails.message)" -ForegroundColor Red
        } else {
            Write-Host "Chi tiết: $($_.ErrorDetails.Message)" -ForegroundColor Red
        }
    }
    exit 1
}

