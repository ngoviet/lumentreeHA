# Script restart HA và kiểm tra integration
# Chạy với: powershell -ExecutionPolicy Bypass -File restart_and_check.ps1

$configPath = "\\192.168.10.15\config"
$integrationPath = "$configPath\custom_components\lumentree"

Write-Host "=== Home Assistant Restart and Integration Check ===" -ForegroundColor Yellow
Write-Host ""

# 1. Kiểm tra file integration
Write-Host "1. Checking integration files..." -ForegroundColor Cyan
$requiredFiles = @("__init__.py", "manifest.json", "config_flow.py", "const.py", "strings.json")
$allFilesOk = $true
foreach ($file in $requiredFiles) {
    $path = Join-Path $integrationPath $file
    if (Test-Path $path) {
        Write-Host "   ✓ $file" -ForegroundColor Green
    } else {
        Write-Host "   ✗ $file MISSING" -ForegroundColor Red
        $allFilesOk = $false
    }
}

if (-not $allFilesOk) {
    Write-Host "`n✗ Some required files are missing!" -ForegroundColor Red
    exit 1
}

# 2. Kiểm tra manifest.json
Write-Host "`n2. Checking manifest.json..." -ForegroundColor Cyan
$manifestPath = Join-Path $integrationPath "manifest.json"
try {
    $manifest = Get-Content $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
    Write-Host "   ✓ Domain: $($manifest.domain)" -ForegroundColor Green
    Write-Host "   ✓ Config Flow: $($manifest.config_flow)" -ForegroundColor Green
    Write-Host "   ✓ Version: $($manifest.version)" -ForegroundColor Green
} catch {
    Write-Host "   ✗ Invalid manifest.json: $_" -ForegroundColor Red
    exit 1
}

# 3. Thử restart HA (nếu có script)
Write-Host "`n3. Attempting to restart Home Assistant..." -ForegroundColor Cyan
$restartScript = Join-Path $configPath "ha-restart-tools\restart_ha.ps1"
if (Test-Path $restartScript) {
    Write-Host "   Found restart script, but execution policy may block it." -ForegroundColor Yellow
    Write-Host "   Please restart HA manually from UI: Settings → System → Restart" -ForegroundColor Yellow
} else {
    Write-Host "   Restart script not found." -ForegroundColor Yellow
    Write-Host "   Please restart HA manually from UI: Settings → System → Restart" -ForegroundColor Yellow
}

Write-Host "`n   Waiting 45 seconds for HA to restart (if you restarted manually)..." -ForegroundColor Cyan
Start-Sleep -Seconds 45

# 4. Kiểm tra logs
Write-Host "`n4. Checking Home Assistant logs..." -ForegroundColor Cyan
$logFiles = @("home-assistant.log", "home-assistant.log.1")
$foundLogs = $false
foreach ($logFile in $logFiles) {
    $logPath = Join-Path $configPath $logFile
    if (Test-Path $logPath) {
        $foundLogs = $true
        Write-Host "`n   Checking $logFile..." -ForegroundColor Gray
        $logContent = Get-Content $logPath -Tail 100 -ErrorAction SilentlyContinue
        if ($logContent) {
            $lumentreeLogs = $logContent | Select-String -Pattern "lumentree|Setting up.*lumentree" -CaseSensitive:$false
            if ($lumentreeLogs) {
                Write-Host "   Found lumentree entries in log:" -ForegroundColor Green
                $lumentreeLogs | Select-Object -Last 5 | ForEach-Object {
                    Write-Host "     $_" -ForegroundColor Gray
                }
            } else {
                Write-Host "   No lumentree entries found in recent logs" -ForegroundColor Yellow
            }
            
            $errors = $logContent | Select-String -Pattern "error.*lumentree|lumentree.*error" -CaseSensitive:$false
            if ($errors) {
                Write-Host "   ⚠ Found errors:" -ForegroundColor Red
                $errors | Select-Object -Last 3 | ForEach-Object {
                    Write-Host "     $_" -ForegroundColor Red
                }
            }
        }
    }
}

if (-not $foundLogs) {
    Write-Host "   No log files found" -ForegroundColor Yellow
}

# 5. Kiểm tra config entries
Write-Host "`n5. Checking config entries..." -ForegroundColor Cyan
$configEntriesFile = Join-Path $configPath ".storage\core.config_entries"
if (Test-Path $configEntriesFile) {
    try {
        $jsonContent = Get-Content $configEntriesFile -Raw -Encoding UTF8
        $json = $jsonContent | ConvertFrom-Json
        $lumentreeEntries = $json.data.entries | Where-Object { $_.domain -eq "lumentree" }
        
        Write-Host "   Found $($lumentreeEntries.Count) lumentree entry/entries:" -ForegroundColor $(if ($lumentreeEntries.Count -gt 0) { "Green" } else { "Yellow" })
        
        if ($lumentreeEntries.Count -gt 0) {
            foreach ($entry in $lumentreeEntries) {
                $stateColor = if ($entry.state -eq "loaded") { "Green" } else { "Yellow" }
                Write-Host "     - Entry ID: $($entry.entry_id)" -ForegroundColor Gray
                Write-Host "       Title: $($entry.title)" -ForegroundColor Gray
                Write-Host "       State: $($entry.state)" -ForegroundColor $stateColor
            }
        } else {
            Write-Host "   No lumentree entries found. You need to add the integration." -ForegroundColor Yellow
        }
    } catch {
        Write-Host "   Error reading config entries: $_" -ForegroundColor Red
    }
} else {
    Write-Host "   Config entries file not found" -ForegroundColor Yellow
}

# 6. Tổng kết
Write-Host "`n=== Summary ===" -ForegroundColor Yellow
Write-Host ""
Write-Host "Integration Structure: " -NoNewline
if ($allFilesOk) {
    Write-Host "✓ OK" -ForegroundColor Green
} else {
    Write-Host "✗ ERRORS FOUND" -ForegroundColor Red
}

Write-Host "`nNext Steps:" -ForegroundColor Cyan
Write-Host "1. If no entries found:" -ForegroundColor White
Write-Host "   - Go to Settings → Devices & Services" -ForegroundColor Gray
Write-Host "   - Click + ADD INTEGRATION" -ForegroundColor Gray
Write-Host "   - Search for lumentree or Lumentree Inverter" -ForegroundColor Gray
Write-Host "   - Fill in Device ID, Device SN, and HTTP Token" -ForegroundColor Gray
Write-Host ""
Write-Host "2. If entries found but not loaded:" -ForegroundColor White
Write-Host "   - Check logs for errors" -ForegroundColor Gray
Write-Host "   - Try reloading the integration" -ForegroundColor Gray
Write-Host ""
Write-Host "3. If integration not found in search:" -ForegroundColor White
Write-Host "   - Clear HA cache and restart" -ForegroundColor Gray
Write-Host "   - Check file permissions" -ForegroundColor Gray
Write-Host "   - Verify HA version >= 2023.1" -ForegroundColor Gray

Write-Host "`n✓ Check completed!" -ForegroundColor Green

