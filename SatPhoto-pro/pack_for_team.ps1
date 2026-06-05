# SatPhoto-Pro pack script for team distribution
# Run in project root: powershell -ExecutionPolicy Bypass -File pack_for_team.ps1

$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot
$Dist = Join-Path $Root "dist"
$Stamp = Get-Date -Format "yyyyMMdd"
$ZipName = "SatPhoto-Pro_team_$Stamp.zip"
$ZipPath = Join-Path $Dist $ZipName
$Stage = Join-Path $Dist "SatPhoto-Pro_stage"

$IncludeItems = @(
    "photogrammetry_suite",
    "task1_code",
    "task2",
    "task4",
    "task5_source",
    "run_task3_all.py",
    "启动系统.bat",
    "launch.bat",
    "安装依赖.bat",
    "README_组员安装与运行.md",
    "pack_for_team.ps1"
)

$IncludeTestCase = $false
if ($IncludeTestCase) {
    $IncludeItems += "全流程测试用例"
}

Write-Host "SatPhoto-Pro packaging..."
Write-Host "Source: $Root"

if (Test-Path $Stage) { Remove-Item $Stage -Recurse -Force }
New-Item -ItemType Directory -Path $Stage -Force | Out-Null
New-Item -ItemType Directory -Path $Dist -Force | Out-Null

foreach ($item in $IncludeItems) {
    $src = Join-Path $Root $item
    if (-not (Test-Path $src)) {
        Write-Warning "Skip missing: $item"
        continue
    }
    $dst = Join-Path $Stage $item
    if ((Get-Item $src).PSIsContainer) {
        Copy-Item $src $dst -Recurse -Force
    } else {
        $parent = Split-Path $dst -Parent
        if (-not (Test-Path $parent)) { New-Item -ItemType Directory -Path $parent -Force | Out-Null }
        Copy-Item $src $dst -Force
    }
    Write-Host "  + $item"
}

$outDir = Join-Path $Stage "suite_outputs"
New-Item -ItemType Directory -Path $outDir -Force | Out-Null
"Output directory for pipeline results." | Set-Content (Join-Path $outDir "README.txt") -Encoding UTF8

$uc = Join-Path $Stage "photogrammetry_suite\user_config.json"
if (Test-Path $uc) { Remove-Item $uc -Force }

Get-ChildItem $Stage -Recurse -Directory -Filter "__pycache__" -ErrorAction SilentlyContinue |
    ForEach-Object { Remove-Item $_.FullName -Recurse -Force }

if (Test-Path $ZipPath) { Remove-Item $ZipPath -Force }
Compress-Archive -Path (Join-Path $Stage "*") -DestinationPath $ZipPath -CompressionLevel Optimal

$mb = [math]::Round((Get-Item $ZipPath).Length / 1MB, 2)
Write-Host ""
Write-Host "Done: $ZipPath"
Write-Host "Size: $mb MB"
Write-Host "Send README_组员安装与运行.md with the zip."

Remove-Item $Stage -Recurse -Force
