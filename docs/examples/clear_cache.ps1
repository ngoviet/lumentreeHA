# Script để clear Home Assistant cache và force reload integration
# Chạy script này khi gặp lỗi "Integration 'lumentree' not found"

$configPath = "\\192.168.10.15\config"

Write-Host "=== Clear Home Assistant Cache ===" -ForegroundColor Yellow

# 1. Stop Home Assistant (nếu đang chạy)
Write-Host "`n1. Checking Home Assistant status..." -ForegroundColor Cyan
# TODO: Add logic to stop HA if needed

# 2. Clear cache directories
Write-Host "`n2. Clearing cache directories..." -ForegroundColor Cyan

$cacheDirs = @(
    "$configPath\.storage\core.config_entries",
    "$configPath\.homeassistant\cache",
    "$configPath\.storage\core.entity_registry"
)

foreach ($dir in $cacheDirs) {
    if (Test-Path $dir) {
        Write-Host "  Removing: $dir" -ForegroundColor Gray
        Remove-Item -Path $dir -Recurse -Force -ErrorAction SilentlyContinue
    } else {
        Write-Host "  Not found: $dir" -ForegroundColor Gray
    }
}

# 3. Verify integration files
Write-Host "`n3. Verifying integration files..." -ForegroundColor Cyan

$requiredFiles = @(
    "$configPath\custom_components\lumentree\__init__.py",
    "$configPath\custom_components\lumentree\manifest.json",
    "$configPath\custom_components\lumentree\strings.json",
    "$configPath\custom_components\lumentree\config_flow.py"
)

$allFilesExist = $true
foreach ($file in $requiredFiles) {
    if (Test-Path $file) {
        Write-Host "  ✓ $file" -ForegroundColor Green
    } else {
        Write-Host "  ✗ Missing: $file" -ForegroundColor Red
        $allFilesExist = $false
    }
}

if (-not $allFilesExist) {
    Write-Host "`n⚠️ Some files are missing! Please check integration installation." -ForegroundColor Red
    exit 1
}

# 4. Validate manifest.json
Write-Host "`n4. Validating manifest.json..." -ForegroundColor Cyan
try {
    $manifest = Get-Content "$configPath\custom_components\lumentree\manifest.json" | ConvertFrom-Json
    if ($manifest.domain -eq "lumentree") {
        Write-Host "  ✓ Domain: $($manifest.domain)" -ForegroundColor Green
        Write-Host "  ✓ Version: $($manifest.version)" -ForegroundColor Green
    } else {
        Write-Host "  ✗ Domain mismatch!" -ForegroundColor Red
        exit 1
    }
} catch {
    Write-Host "  ✗ Invalid JSON: $_" -ForegroundColor Red
    exit 1
}

Write-Host "`n=== Cache cleared successfully ===" -ForegroundColor Green
Write-Host "`nNext steps:" -ForegroundColor Yellow
Write-Host "1. Start Home Assistant" -ForegroundColor White
Write-Host "2. Go to Settings > Devices & Services" -ForegroundColor White
Write-Host "3. Find 'Lumentree Inverter' and click Reload" -ForegroundColor White
Write-Host "4. Or Delete and re-add the integration" -ForegroundColor White

