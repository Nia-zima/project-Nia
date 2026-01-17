
$destination = "AI_Buddy_Source_Backup_$(Get-Date -Format 'yyyyMMdd_HHmmss').zip"
$sourceDir = "c:\Users\jk023\Desktop\AI_Buddy"
$tempDir = Join-Path $env:TEMP "AI_Buddy_Pack"

if (Test-Path $tempDir) { Remove-Item -Recurse -Force $tempDir }
New-Item -ItemType Directory -Path $tempDir

$excludeList = @(
    ".venv",
    "node_modules",
    ".next",
    "__pycache__",
    ".pytest_cache",
    ".git",
    "backups",
    "AI_Buddy_Backup_Refactored.zip",
    "chat_history.db" # データベースは大きいので除外（必要なら別途バックアップ）
)

Filter Test-Exclude {
    param($item)
    foreach ($exclude in $excludeList) {
        if ($item.FullName -like "*\$exclude*" -or $item.Name -eq $exclude) {
            return $false
        }
    }
    return $true
}

Get-ChildItem -Path $sourceDir -Recurse | Where-Object { Test-Exclude $_ } | ForEach-Object {
    $targetPath = Join-Path $tempDir $_.FullName.Substring($sourceDir.Length + 1)
    if ($_.PSIsContainer) {
        if (-not (Test-Path $targetPath)) {
            New-Item -ItemType Directory -Path $targetPath
        }
    } else {
        $parent = Split-Path $targetPath
        if (-not (Test-Path $parent)) {
            New-Item -ItemType Directory -Path $parent
        }
        Copy-Item $_.FullName $targetPath
    }
}

Compress-Archive -Path "$tempDir\*" -DestinationPath (Join-Path $sourceDir $destination) -Force
Remove-Item -Recurse -Force $tempDir

Write-Host "Backup created: $destination"
