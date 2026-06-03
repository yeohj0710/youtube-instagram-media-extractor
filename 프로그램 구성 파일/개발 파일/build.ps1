$ErrorActionPreference = "Stop"

$DevRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProgramFilesDir = Split-Path -Parent $DevRoot
$RepoRoot = Split-Path -Parent $ProgramFilesDir
$ProgramDirName = -join ([char[]](0xD504, 0xB85C, 0xADF8, 0xB7A8, 0x20, 0xAD6C, 0xC131, 0x20, 0xD30C, 0xC77C))
$OutputDirName = (-join ([char[]](0xB2E4, 0xC6B4, 0xB85C, 0xB4DC, 0xD55C))) + " " + (-join ([char[]](0xBBF8, 0xB514, 0xC5B4)))
$ExeBaseName = "YouTube" + ([char]0x00B7) + "Instagram " + (-join ([char[]](0xBBF8, 0xB514, 0xC5B4))) + " " + (-join ([char[]](0xCD94, 0xCD9C, 0xAE30)))
$ExeFileName = $ExeBaseName + ".exe"

Set-Location -LiteralPath $DevRoot

if (-not (Test-Path -LiteralPath ".venv")) {
    python -m venv .venv
}

function Invoke-Python {
    param(
        [Parameter(ValueFromRemainingArguments = $true)]
        [string[]]$Arguments
    )

    & ".\.venv\Scripts\python.exe" @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Python command failed with exit code ${LASTEXITCODE}: python $($Arguments -join ' ')"
    }
}

Invoke-Python -m pip install --upgrade --ignore-installed --no-deps pip
Invoke-Python -m pip install -r requirements.txt pytest
Invoke-Python -m pytest

if (Test-Path -LiteralPath "build") {
    Remove-Item -LiteralPath "build" -Recurse -Force
}
if (Test-Path -LiteralPath "dist") {
    Remove-Item -LiteralPath "dist" -Recurse -Force
}

Invoke-Python -m PyInstaller `
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

if (-not (Test-Path -LiteralPath $BuiltExe)) {
    throw "Built exe was not found: $BuiltExe"
}
if (-not (Test-Path -LiteralPath $BuiltRuntimeDir)) {
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
    if (Test-Path -LiteralPath $OldExe) {
        Remove-Item -LiteralPath $OldExe -Force
    }
}
Copy-Item -LiteralPath $BuiltExe -Destination (Join-Path $RepoRoot $ExeFileName) -Force

[System.IO.Directory]::CreateDirectory($ProgramFilesDir) | Out-Null
$DevRootResolved = (Resolve-Path -LiteralPath $DevRoot).Path
Get-ChildItem -LiteralPath $ProgramFilesDir -Force | ForEach-Object {
    $ItemPath = (Resolve-Path -LiteralPath $_.FullName).Path
    if ($ItemPath -ne $DevRootResolved) {
        Remove-Item -LiteralPath $_.FullName -Recurse -Force
    }
}
Get-ChildItem -LiteralPath $BuiltRuntimeDir -Force | Copy-Item -Destination $ProgramFilesDir -Recurse -Force

$DownloadHelpImage = Join-Path $DevRoot "assets\github-download-zip.png"
if (Test-Path -LiteralPath $DownloadHelpImage) {
    Copy-Item -LiteralPath $DownloadHelpImage -Destination (Join-Path $ProgramFilesDir "github-download-zip.png") -Force
}

[System.IO.Directory]::CreateDirectory((Join-Path $RepoRoot $OutputDirName)) | Out-Null

Write-Host ""
Write-Host "Done:"
Write-Host ("  " + $ExeFileName)
Write-Host ("  " + $OutputDirName + "\")
Write-Host ("  " + $ProgramDirName + "\")
