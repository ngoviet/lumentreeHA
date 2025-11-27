# Script để kiểm tra và khôi phục Lumentree integration

$configPath = "\\192.168.10.15\config"
$configEntriesFile = "$configPath\.storage\core.config_entries"

Write-Host "=== Lumentree: Check and Restore ===" -ForegroundColor Yellow
Write-Host ""

# 1. Kiểm tra entries hiện tại
Write-Host "1. Checking current entries..." -ForegroundColor Cyan
try {
    $jsonContent = Get-Content $configEntriesFile -Raw -Encoding UTF8
    $json = $jsonContent | ConvertFrom-Json
    $lumentreeEntries = $json.data.entries | Where-Object { $_.domain -eq 'lumentree' }
    
    Write-Host "   Found $($lumentreeEntries.Count) lumentree entry/entries" -ForegroundColor $(if ($lumentreeEntries.Count -eq 0) { "Red" } else { "Green" })
    
    if ($lumentreeEntries.Count -gt 0) {
        $lumentreeEntries | ForEach-Object {
            Write-Host "   - Entry ID: $($_.entry_id)" -ForegroundColor Gray
            Write-Host "     Title: $($_.title)" -ForegroundColor Gray
            Write-Host "     State: $($_.state)" -ForegroundColor $(if ($_.state -eq 'loaded') { "Green" } else { "Yellow" })
            Write-Host "     Device ID: $($_.data.device_id)" -ForegroundColor Gray
        }
    }
} catch {
    Write-Host "   ERROR: Failed to read config: $_" -ForegroundColor Red
    exit 1
}

# 2. Kiểm tra backup
Write-Host "`n2. Checking for backups..." -ForegroundColor Cyan
$backups = Get-ChildItem "$configEntriesFile.backup.*" -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending

if ($backups.Count -eq 0) {
    Write-Host "   No backup files found." -ForegroundColor Yellow
    Write-Host "`n3. Next steps:" -ForegroundColor Cyan
    Write-Host "   You need to add the integration again from UI:" -ForegroundColor White
    Write-Host "   1. Go to Settings → Devices & Services" -ForegroundColor Gray
    Write-Host "   2. Click '+ ADD INTEGRATION'" -ForegroundColor Gray
    Write-Host "   3. Search for 'lumentree' or 'Lumentree Inverter'" -ForegroundColor Gray
    Write-Host "   4. Fill in the required information:" -ForegroundColor Gray
    Write-Host "      - Device ID (e.g., H240909079)" -ForegroundColor Gray
    Write-Host "      - Device SN (e.g., 01K99JBTP1Q9ERQ1BESFXD700R)" -ForegroundColor Gray
    Write-Host "      - HTTP Token" -ForegroundColor Gray
    exit 0
}

Write-Host "   Found $($backups.Count) backup file(s):" -ForegroundColor Green
$backups | Select-Object -First 5 | ForEach-Object {
    Write-Host "   - $($_.Name)" -ForegroundColor Gray
    Write-Host "     Created: $($_.LastWriteTime)" -ForegroundColor Gray
}

# 3. Nếu không có entry, hỏi có muốn restore không
if ($lumentreeEntries.Count -eq 0) {
    Write-Host "`n3. No lumentree entries found!" -ForegroundColor Red
    Write-Host "   Do you want to restore from backup?" -ForegroundColor Yellow
    
    $latestBackup = $backups[0]
    Write-Host "`n   Latest backup: $($latestBackup.Name)" -ForegroundColor Cyan
    Write-Host "   Created: $($latestBackup.LastWriteTime)" -ForegroundColor Gray
    
    $confirm = Read-Host "`n   Restore from this backup? (yes/no)"
    if ($confirm -eq 'yes' -or $confirm -eq 'y') {
        Write-Host "`n4. Restoring from backup..." -ForegroundColor Cyan
        try {
            # Backup file hiện tại trước
            $currentBackup = "$configEntriesFile.current.$(Get-Date -Format 'yyyyMMdd_HHmmss')"
            Copy-Item $configEntriesFile $currentBackup -Force
            Write-Host "   Current file backed up to: $currentBackup" -ForegroundColor Green
            
            # Restore từ backup
            Copy-Item $latestBackup.FullName $configEntriesFile -Force
            Write-Host "   ✓ Restored from: $($latestBackup.Name)" -ForegroundColor Green
            Write-Host "`n5. Next steps:" -ForegroundColor Cyan
            Write-Host "   Please restart Home Assistant:" -ForegroundColor White
            Write-Host "   - Go to Settings → System → Restart" -ForegroundColor Gray
            Write-Host "   - Or run: .\ha-restart-tools\restart_ha.ps1" -ForegroundColor Gray
        } catch {
            Write-Host "   ERROR: Failed to restore: $_" -ForegroundColor Red
            exit 1
        }
    } else {
        Write-Host "`n   Operation cancelled." -ForegroundColor Yellow
        Write-Host "   You can add the integration again from UI." -ForegroundColor White
    }
} else {
    Write-Host "`n3. Entries found. No restore needed." -ForegroundColor Green
    if ($lumentreeEntries | Where-Object { $_.state -ne 'loaded' }) {
        Write-Host "   However, some entries are not loaded." -ForegroundColor Yellow
        Write-Host "   You may want to restart Home Assistant." -ForegroundColor White
    }
}

Write-Host "`n✓ Script completed!" -ForegroundColor Green

