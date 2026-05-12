$ErrorActionPreference = "Stop"

$DevRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProgramFilesDir = Split-Path -Parent $DevRoot
$RepoRoot = Split-Path -Parent $ProgramFilesDir
$ProgramDirName = -join ([char[]](0xD504, 0xB85C, 0xADF8, 0xB7A8, 0x20, 0xAD6C, 0xC131, 0x20, 0xD30C, 0xC77C))
$OutputDirName = (-join ([char[]](0xB2E4, 0xC6B4, 0xB85C, 0xB4DC, 0xD55C))) + " " + (-join ([char[]](0xBBF8, 0xB514, 0xC5B4)))
$ExeBaseName = "YouTube" + ([char]0x00B7) + "Instagram " + (-join ([char[]](0xBBF8, 0xB514, 0xC5B4))) + " " + (-join ([char[]](0xCD94, 0xCD9C, 0xAE30)))
$ExeFileName = $ExeBaseName + ".exe"

Set-Location $DevRoot

if (-not (Test-Path ".venv")) {
    python -m venv .venv
}

& ".\.venv\Scripts\python.exe" -m pip install --upgrade pip
& ".\.venv\Scripts\python.exe" -m pip install -r requirements.txt pytest
& ".\.venv\Scripts\python.exe" -m pytest

if (Test-Path "build") {
    Remove-Item -LiteralPath "build" -Recurse -Force
}
if (Test-Path "dist") {
    Remove-Item -LiteralPath "dist" -Recurse -Force
}

& ".\.venv\Scripts\python.exe" -m PyInstaller `
    --noconfirm `
    --clean `
    --onedir `
    --windowed `
    --name $ExeBaseName `
    --icon "assets\youtube-instagram-media.ico" `
    --contents-directory $ProgramDirName `
    --add-data "assets\youtube-instagram-media.ico;assets" `
    --add-data "assets\youtube-instagram-media.png;assets" `
    --collect-all customtkinter `
    --collect-binaries imageio_ffmpeg `
    --hidden-import yt_dlp `
    "src\youtube_instagram_media_extractor\__main__.py"

$BuiltAppDir = Join-Path $DevRoot ("dist\" + $ExeBaseName)
$BuiltExe = Join-Path $BuiltAppDir $ExeFileName
$BuiltRuntimeDir = Join-Path $BuiltAppDir $ProgramDirName

if (-not (Test-Path $BuiltExe)) {
    throw "Built exe was not found: $BuiltExe"
}
if (-not (Test-Path $BuiltRuntimeDir)) {
    throw "Built runtime folder was not found: $BuiltRuntimeDir"
}

$ExtractorName = -join ([char[]](0xCD94, 0xCD9C, 0xAE30))
$MediaName = -join ([char[]](0xBBF8, 0xB514, 0xC5B4))
$OldExeNames = @(
    ("YouTube " + $MediaName + " " + $ExtractorName + ".exe"),
    ("YouTube MP3 MP4 " + $ExtractorName + ".exe"),
    ("YouTube MP3 " + $ExtractorName + ".exe")
)
foreach ($OldExeName in $OldExeNames) {
    $OldExe = Join-Path $RepoRoot $OldExeName
    if (Test-Path $OldExe) {
        Remove-Item -LiteralPath $OldExe -Force
    }
}
Copy-Item $BuiltExe (Join-Path $RepoRoot $ExeFileName) -Force

New-Item -ItemType Directory -Force -Path $ProgramFilesDir | Out-Null
$DevRootResolved = (Resolve-Path $DevRoot).Path
Get-ChildItem $ProgramFilesDir -Force | ForEach-Object {
    $ItemPath = (Resolve-Path $_.FullName).Path
    if ($ItemPath -ne $DevRootResolved) {
        Remove-Item -LiteralPath $_.FullName -Recurse -Force
    }
}
Copy-Item (Join-Path $BuiltRuntimeDir "*") $ProgramFilesDir -Recurse -Force

New-Item -ItemType Directory -Force -Path (Join-Path $RepoRoot $OutputDirName) | Out-Null

Write-Host ""
Write-Host "Done:"
Write-Host ("  " + $ExeFileName)
Write-Host ("  " + $OutputDirName + "\")
Write-Host ("  " + $ProgramDirName + "\")
