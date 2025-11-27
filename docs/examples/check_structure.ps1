# Script kiểm tra toàn bộ cấu trúc Integration Lumentree
# Chạy script này để tìm lỗi cấu trúc có thể khiến integration không hiển thị

$configPath = "\\192.168.10.15\config"
$integrationPath = "$configPath\custom_components\lumentree"

Write-Host "=== Lumentree Integration Structure Check ===" -ForegroundColor Yellow
Write-Host ""

$errors = @()
$warnings = @()
$info = @()

# 1. Kiểm tra file bắt buộc
Write-Host "1. Checking required files..." -ForegroundColor Cyan
$requiredFiles = @(
    "__init__.py",
    "manifest.json",
    "config_flow.py",
    "const.py",
    "strings.json",
    "sensor.py",
    "binary_sensor.py"
)

foreach ($file in $requiredFiles) {
    $path = Join-Path $integrationPath $file
    if (Test-Path $path) {
        Write-Host "   ✓ $file" -ForegroundColor Green
    } else {
        Write-Host "   ✗ $file MISSING" -ForegroundColor Red
        $errors += "Missing required file: $file"
    }
}

# 2. Kiểm tra manifest.json
Write-Host "`n2. Checking manifest.json..." -ForegroundColor Cyan
$manifestPath = Join-Path $integrationPath "manifest.json"
if (Test-Path $manifestPath) {
    try {
        $manifest = Get-Content $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
        
        # Kiểm tra các field bắt buộc
        $requiredFields = @("domain", "name", "config_flow", "version")
        foreach ($field in $requiredFields) {
            if ($manifest.PSObject.Properties.Name -contains $field) {
                Write-Host "   ✓ $field = $($manifest.$field)" -ForegroundColor Green
            } else {
                Write-Host "   ✗ Missing field: $field" -ForegroundColor Red
                $errors += "manifest.json missing field: $field"
            }
        }
        
        # Kiểm tra domain
        if ($manifest.domain -eq "lumentree") {
            Write-Host "   ✓ domain is 'lumentree'" -ForegroundColor Green
        } else {
            Write-Host "   ✗ domain is '$($manifest.domain)', expected 'lumentree'" -ForegroundColor Red
            $errors += "manifest.json domain mismatch: $($manifest.domain)"
        }
        
        # Kiểm tra config_flow
        if ($manifest.config_flow -eq $true) {
            Write-Host "   ✓ config_flow is true" -ForegroundColor Green
        } else {
            Write-Host "   ⚠ config_flow is false" -ForegroundColor Yellow
            $warnings += "config_flow is false in manifest.json"
        }
        
    } catch {
        Write-Host "   ✗ Invalid JSON: $_" -ForegroundColor Red
        $errors += "manifest.json is invalid JSON: $_"
    }
} else {
    Write-Host "   ✗ manifest.json not found" -ForegroundColor Red
    $errors += "manifest.json not found"
}

# 3. Kiểm tra const.py
Write-Host "`n3. Checking const.py..." -ForegroundColor Cyan
$constPath = Join-Path $integrationPath "const.py"
if (Test-Path $constPath) {
    $constContent = Get-Content $constPath -Raw
    if ($constContent -match "DOMAIN.*=.*['\`"]lumentree['\`"]") {
        Write-Host "   ✓ DOMAIN = 'lumentree'" -ForegroundColor Green
    } else {
        Write-Host "   ✗ DOMAIN not found or incorrect" -ForegroundColor Red
        $errors += "const.py DOMAIN not found or incorrect"
    }
} else {
    Write-Host "   ✗ const.py not found" -ForegroundColor Red
    $errors += "const.py not found"
}

# 4. Kiểm tra config_flow.py
Write-Host "`n4. Checking config_flow.py..." -ForegroundColor Cyan
$configFlowPath = Join-Path $integrationPath "config_flow.py"
if (Test-Path $configFlowPath) {
    $configFlowContent = Get-Content $configFlowPath -Raw
    if ($configFlowContent -match "class.*ConfigFlow") {
        Write-Host "   ✓ ConfigFlow class found" -ForegroundColor Green
    } else {
        Write-Host "   ✗ ConfigFlow class not found" -ForegroundColor Red
        $errors += "config_flow.py missing ConfigFlow class"
    }
    
    if ($configFlowContent -match "domain\s*=\s*DOMAIN") {
        Write-Host "   ✓ domain=DOMAIN found" -ForegroundColor Green
    } else {
        Write-Host "   ⚠ domain=DOMAIN not found" -ForegroundColor Yellow
        $warnings += "config_flow.py may not have domain=DOMAIN"
    }
} else {
    Write-Host "   ✗ config_flow.py not found" -ForegroundColor Red
    $errors += "config_flow.py not found"
}

# 5. Kiểm tra __init__.py
Write-Host "`n5. Checking __init__.py..." -ForegroundColor Cyan
$initPath = Join-Path $integrationPath "__init__.py"
if (Test-Path $initPath) {
    $initContent = Get-Content $initPath -Raw
    
    if ($initContent -match "async def async_setup\(") {
        Write-Host "   ✓ async_setup() found" -ForegroundColor Green
    } else {
        Write-Host "   ⚠ async_setup() not found" -ForegroundColor Yellow
        $warnings += "__init__.py missing async_setup()"
    }
    
    if ($initContent -match "async def async_setup_entry\(") {
        Write-Host "   ✓ async_setup_entry() found" -ForegroundColor Green
    } else {
        Write-Host "   ✗ async_setup_entry() not found" -ForegroundColor Red
        $errors += "__init__.py missing async_setup_entry()"
    }
} else {
    Write-Host "   ✗ __init__.py not found" -ForegroundColor Red
    $errors += "__init__.py not found"
}

# 6. Kiểm tra syntax errors
Write-Host "`n6. Checking Python syntax..." -ForegroundColor Cyan
$pythonFiles = @("__init__.py", "config_flow.py", "const.py")
foreach ($file in $pythonFiles) {
    $path = Join-Path $integrationPath $file
    if (Test-Path $path) {
        try {
            $result = python -m py_compile $path 2>&1
            if ($LASTEXITCODE -eq 0) {
                Write-Host "   ✓ $file - No syntax errors" -ForegroundColor Green
            } else {
                Write-Host "   ✗ $file - Syntax errors found" -ForegroundColor Red
                $errors += "$file has syntax errors: $result"
            }
        } catch {
            Write-Host "   ⚠ $file - Could not check syntax" -ForegroundColor Yellow
            $warnings += "Could not check syntax for $file"
        }
    }
}

# 7. Kiểm tra cấu trúc thư mục
Write-Host "`n7. Checking directory structure..." -ForegroundColor Cyan
$requiredDirs = @("core", "entities", "coordinators", "services", "models")
foreach ($dir in $requiredDirs) {
    $dirPath = Join-Path $integrationPath $dir
    if (Test-Path $dirPath) {
        Write-Host "   ✓ $dir/" -ForegroundColor Green
    } else {
        Write-Host "   ⚠ $dir/ not found" -ForegroundColor Yellow
        $warnings += "Directory $dir/ not found"
    }
}

# 8. Kiểm tra strings.json
Write-Host "`n8. Checking strings.json..." -ForegroundColor Cyan
$stringsPath = Join-Path $integrationPath "strings.json"
if (Test-Path $stringsPath) {
    try {
        $strings = Get-Content $stringsPath -Raw -Encoding UTF8 | ConvertFrom-Json
        Write-Host "   ✓ strings.json is valid JSON" -ForegroundColor Green
    } catch {
        Write-Host "   ✗ strings.json is invalid JSON" -ForegroundColor Red
        $errors += "strings.json is invalid JSON: $_"
    }
} else {
    Write-Host "   ⚠ strings.json not found" -ForegroundColor Yellow
    $warnings += "strings.json not found"
}

# 9. Tổng kết
Write-Host "`n=== Summary ===" -ForegroundColor Yellow
if ($errors.Count -eq 0 -and $warnings.Count -eq 0) {
    Write-Host "✓ All checks passed! Integration structure is correct." -ForegroundColor Green
    Write-Host "`nIf integration still doesn't appear:" -ForegroundColor Cyan
    Write-Host "1. Clear HA cache and restart" -ForegroundColor White
    Write-Host "2. Check HA logs for errors" -ForegroundColor White
    Write-Host "3. Verify file permissions" -ForegroundColor White
} else {
    if ($errors.Count -gt 0) {
        Write-Host "`n✗ ERRORS found ($($errors.Count)):" -ForegroundColor Red
        foreach ($error in $errors) {
            Write-Host "  - $error" -ForegroundColor Red
        }
    }
    
    if ($warnings.Count -gt 0) {
        Write-Host "`n⚠ WARNINGS ($($warnings.Count)):" -ForegroundColor Yellow
        foreach ($warning in $warnings) {
            Write-Host "  - $warning" -ForegroundColor Yellow
        }
    }
    
    Write-Host "`nPlease fix the errors above before using the integration." -ForegroundColor Red
}

Write-Host "`n✓ Check completed!" -ForegroundColor Green

