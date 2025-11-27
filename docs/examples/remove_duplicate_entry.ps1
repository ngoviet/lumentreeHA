# Script để xóa entry duplicate "Not loaded" của Lumentree integration
# Chạy script này khi có entry "Not loaded" trong UI

$configPath = "\\192.168.10.15\config"
$configEntriesFile = "$configPath\.storage\core.config_entries"
$backupFile = "$configEntriesFile.backup.$(Get-Date -Format 'yyyyMMdd_HHmmss')"

Write-Host "=== Lumentree: Remove Duplicate/Not Loaded Entry ===" -ForegroundColor Yellow
Write-Host ""

# 1. Kiểm tra file tồn tại
if (-not (Test-Path $configEntriesFile)) {
    Write-Host "ERROR: Config entries file not found: $configEntriesFile" -ForegroundColor Red
    exit 1
}

Write-Host "1. Reading config entries..." -ForegroundColor Cyan
try {
    $jsonContent = Get-Content $configEntriesFile -Raw -Encoding UTF8
    $json = $jsonContent | ConvertFrom-Json
} catch {
    Write-Host "ERROR: Failed to parse JSON: $_" -ForegroundColor Red
    exit 1
}

# 2. Tìm tất cả lumentree entries
$lumentreeEntries = $json.data.entries | Where-Object { $_.domain -eq 'lumentree' }

if ($lumentreeEntries.Count -eq 0) {
    Write-Host "No lumentree entries found." -ForegroundColor Yellow
    exit 0
}

Write-Host "`n2. Found $($lumentreeEntries.Count) lumentree entry/entries:" -ForegroundColor Cyan
$lumentreeEntries | ForEach-Object {
    $entry = $_
    $deviceId = $entry.data.device_id
    $deviceSn = $entry.data.device_sn
    $state = $entry.state
    $title = $entry.title
    
    $statusColor = if ($state -eq 'loaded') { "Green" } elseif ($state -eq 'not_loaded' -or $state -eq 'setup_error') { "Red" } else { "Yellow" }
    
    Write-Host "  - Entry ID: $($entry.entry_id)" -ForegroundColor Gray
    Write-Host "    Title: $title" -ForegroundColor Gray
    Write-Host "    State: $state" -ForegroundColor $statusColor
    Write-Host "    Device ID: $deviceId" -ForegroundColor Gray
    Write-Host "    Device SN: $deviceSn" -ForegroundColor Gray
    Write-Host ""
}

# 3. Xác định entry cần xóa
$entriesToRemove = @()

# Tìm entry có state "not_loaded" hoặc "setup_error"
$notLoadedEntries = $lumentreeEntries | Where-Object { 
    $_.state -eq 'not_loaded' -or $_.state -eq 'setup_error' 
}

if ($notLoadedEntries.Count -gt 0) {
    Write-Host "3. Found $($notLoadedEntries.Count) entry/entries with 'not_loaded' or 'setup_error' state:" -ForegroundColor Cyan
    $notLoadedEntries | ForEach-Object {
        Write-Host "  - $($_.entry_id): $($_.title) (State: $($_.state))" -ForegroundColor Yellow
        $entriesToRemove += $_
    }
}

# Nếu có nhiều hơn 1 entry và không có entry "not_loaded", tìm duplicate
if ($entriesToRemove.Count -eq 0 -and $lumentreeEntries.Count -gt 1) {
    Write-Host "`n3. No 'not_loaded' entries found. Checking for duplicates..." -ForegroundColor Cyan
    
    # Nhóm theo device_id hoặc device_sn
    $grouped = $lumentreeEntries | Group-Object { $_.data.device_id }
    
    foreach ($group in $grouped) {
        if ($group.Count -gt 1) {
            Write-Host "  Found $($group.Count) entries for Device ID: $($group.Name)" -ForegroundColor Yellow
            
            # Giữ entry có state "loaded", xóa các entry khác
            $loadedEntry = $group.Group | Where-Object { $_.state -eq 'loaded' } | Select-Object -First 1
            $otherEntries = $group.Group | Where-Object { $_.entry_id -ne $loadedEntry.entry_id }
            
            if ($loadedEntry) {
                Write-Host "    Keeping entry: $($loadedEntry.entry_id) (State: loaded)" -ForegroundColor Green
                $otherEntries | ForEach-Object {
                    Write-Host "    Will remove: $($_.entry_id) (State: $($_.state))" -ForegroundColor Red
                    $entriesToRemove += $_
                }
            } else {
                # Không có entry loaded, giữ entry mới nhất (entry_id lớn nhất hoặc created_at mới nhất)
                $sorted = $group.Group | Sort-Object { $_.entry_id } -Descending
                $keepEntry = $sorted[0]
                Write-Host "    No 'loaded' entry found. Keeping newest: $($keepEntry.entry_id)" -ForegroundColor Yellow
                $sorted[1..($sorted.Count-1)] | ForEach-Object {
                    Write-Host "    Will remove: $($_.entry_id) (State: $($_.state))" -ForegroundColor Red
                    $entriesToRemove += $_
                }
            }
        }
    }
}

# 4. Xác nhận và xóa
if ($entriesToRemove.Count -eq 0) {
    Write-Host "`n✓ No duplicate or 'not_loaded' entries found. Nothing to remove." -ForegroundColor Green
    exit 0
}

Write-Host "`n4. Summary:" -ForegroundColor Cyan
Write-Host "  Entries to remove: $($entriesToRemove.Count)" -ForegroundColor Yellow
$entriesToRemove | ForEach-Object {
    Write-Host "    - $($_.entry_id): $($_.title) (State: $($_.state))" -ForegroundColor Red
}

Write-Host "`n5. Confirmation:" -ForegroundColor Cyan
$confirm = Read-Host "Do you want to remove these entries? (yes/no)"
if ($confirm -ne 'yes' -and $confirm -ne 'y') {
    Write-Host "Operation cancelled." -ForegroundColor Yellow
    exit 0
}

# 5. Backup
Write-Host "`n6. Creating backup..." -ForegroundColor Cyan
try {
    Copy-Item $configEntriesFile $backupFile -Force
    Write-Host "  Backup created: $backupFile" -ForegroundColor Green
} catch {
    Write-Host "  ERROR: Failed to create backup: $_" -ForegroundColor Red
    exit 1
}

# 6. Xóa entries
Write-Host "`n7. Removing entries..." -ForegroundColor Cyan
$removedCount = 0
$entryIdsToRemove = $entriesToRemove | ForEach-Object { $_.entry_id }

$json.data.entries = $json.data.entries | Where-Object { 
    $entry = $_
    $shouldKeep = $entry.domain -ne 'lumentree' -or $entry.entry_id -notin $entryIdsToRemove
    
    if (-not $shouldKeep -and $entry.domain -eq 'lumentree') {
        Write-Host "  Removed: $($entry.entry_id) - $($entry.title)" -ForegroundColor Red
        $removedCount++
    }
    
    return $shouldKeep
}

# 7. Lưu lại
Write-Host "`n8. Saving changes..." -ForegroundColor Cyan
try {
    # Convert to JSON với format đẹp
    $jsonContent = $json | ConvertTo-Json -Depth 20
    
    # Lưu file
    [System.IO.File]::WriteAllText($configEntriesFile, $jsonContent, [System.Text.Encoding]::UTF8)
    
    Write-Host "  ✓ Successfully removed $removedCount entry/entries" -ForegroundColor Green
    Write-Host "  ✓ Changes saved to: $configEntriesFile" -ForegroundColor Green
} catch {
    Write-Host "  ERROR: Failed to save changes: $_" -ForegroundColor Red
    Write-Host "  Restoring from backup..." -ForegroundColor Yellow
    Copy-Item $backupFile $configEntriesFile -Force
    exit 1
}

# 8. Hướng dẫn
Write-Host "`n9. Next steps:" -ForegroundColor Cyan
Write-Host "  1. Restart Home Assistant:" -ForegroundColor White
Write-Host "     - Go to Settings → System → Restart" -ForegroundColor Gray
Write-Host "     - Or run: .\ha-restart-tools\restart_ha.ps1" -ForegroundColor Gray
Write-Host "  2. After restart, check UI:" -ForegroundColor White
Write-Host "     - Go to Settings → Devices & Services → Lumentree" -ForegroundColor Gray
Write-Host "     - Verify only 1 entry remains (should be 'loaded')" -ForegroundColor Gray
Write-Host "  3. If something goes wrong, restore backup:" -ForegroundColor White
Write-Host "     Copy-Item '$backupFile' '$configEntriesFile' -Force" -ForegroundColor Gray

Write-Host "`n✓ Script completed successfully!" -ForegroundColor Green

