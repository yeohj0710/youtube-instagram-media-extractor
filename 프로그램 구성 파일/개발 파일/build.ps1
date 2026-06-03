$ErrorActionPreference = "Stop"

$DevRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProgramFilesDir = Split-Path -Parent $DevRoot
$RepoRoot = Split-Path -Parent $ProgramFilesDir
$LocalBuildRoot = Join-Path ([System.IO.Path]::GetTempPath()) "youtube_instagram_media_extractor_build"
$BuildDir = Join-Path $LocalBuildRoot "build"
$DistDir = Join-Path $LocalBuildRoot "dist"
$ProgramDirName = -join ([char[]](0xD504, 0xB85C, 0xADF8, 0xB7A8, 0x20, 0xAD6C, 0xC131, 0x20, 0xD30C, 0xC77C))
$OutputDirName = (-join ([char[]](0xB2E4, 0xC6B4, 0xB85C, 0xB4DC, 0xD55C))) + " " + (-join ([char[]](0xBBF8, 0xB514, 0xC5B4)))
$ExeBaseName = "YouTube" + ([char]0x00B7) + "Instagram " + (-join ([char[]](0xBBF8, 0xB514, 0xC5B4))) + " " + (-join ([char[]](0xCD94, 0xCD9C, 0xAE30)))
$ExeFileName = $ExeBaseName + ".exe"

Set-Location -LiteralPath $DevRoot

function Test-PythonCommand {
    param([string]$Command)

    if (-not $Command) {
        return $false
    }
    & $Command --version *> $null
    return $LASTEXITCODE -eq 0
}

function Resolve-PythonCommand {
    $Candidates = @()
    if ($env:PYTHON) {
        $Candidates += $env:PYTHON
    }
    foreach ($Name in @("python", "py")) {
        $Command = Get-Command $Name -ErrorAction SilentlyContinue
        if ($Command) {
            $Candidates += $Command.Source
        }
    }
    foreach ($Candidate in ($Candidates | Select-Object -Unique)) {
        if (Test-PythonCommand $Candidate) {
            return $Candidate
        }
    }
    throw "Python 3.11 이상을 찾을 수 없습니다. python 설치 또는 PYTHON 환경 변수 지정이 필요합니다."
}

$PythonCommand = Resolve-PythonCommand
$VenvPython = Join-Path $DevRoot ".venv\Scripts\python.exe"

function Test-VenvPython {
    if (-not (Test-Path -LiteralPath $VenvPython)) {
        return $false
    }
    try {
        & $VenvPython -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)" *> $null
        return $LASTEXITCODE -eq 0
    }
    catch {
        return $false
    }
}

if (-not (Test-VenvPython)) {
    if (Test-Path -LiteralPath ".venv") {
        Remove-Item -LiteralPath ".venv" -Recurse -Force
    }
    & $PythonCommand -m venv .venv
    if ($LASTEXITCODE -ne 0) {
        throw "Python virtual environment creation failed with exit code ${LASTEXITCODE}."
    }
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

function Invoke-PythonOutput {
    param(
        [Parameter(ValueFromRemainingArguments = $true)]
        [string[]]$Arguments
    )

    $Output = & ".\.venv\Scripts\python.exe" @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Python command failed with exit code ${LASTEXITCODE}: python $($Arguments -join ' ')"
    }
    return ($Output -join "`n").Trim()
}

Invoke-Python -m pip install --upgrade --ignore-installed --no-deps pip
Invoke-Python -m pip install -r requirements.txt pytest
Invoke-Python -m pytest
$ImageioFfmpegDir = Join-Path $DevRoot ".venv\Lib\site-packages\imageio_ffmpeg\binaries"
$FfmpegExeItem = Get-ChildItem -LiteralPath $ImageioFfmpegDir -Filter "ffmpeg*.exe" -File | Select-Object -First 1
if (-not $FfmpegExeItem) {
    throw "FFmpeg binary from imageio_ffmpeg was not found: $ImageioFfmpegDir"
}
$FfmpegExe = $FfmpegExeItem.FullName

if (Test-Path -LiteralPath $BuildDir) {
    Remove-Item -LiteralPath $BuildDir -Recurse -Force
}
if (Test-Path -LiteralPath $DistDir) {
    Remove-Item -LiteralPath $DistDir -Recurse -Force
}

$PythonTclRoot = Invoke-PythonOutput -c "import sys; from pathlib import Path; print(Path(sys.base_prefix) / 'tcl')"
$TclDataDir = Join-Path $PythonTclRoot "tcl8.6"
$TkDataDir = Join-Path $PythonTclRoot "tk8.6"
$TclModulesDir = Join-Path $PythonTclRoot "tcl8"
foreach ($RequiredDir in @($TclDataDir, $TkDataDir, $TclModulesDir)) {
    if (-not (Test-Path -LiteralPath $RequiredDir)) {
        throw "Required Tcl/Tk data directory was not found: $RequiredDir"
    }
}

Invoke-Python -m PyInstaller `
    --noconfirm `
    --clean `
    --noupx `
    --onedir `
    --windowed `
    --workpath $BuildDir `
    --distpath $DistDir `
    --specpath $DevRoot `
    --name $ExeBaseName `
    --icon "assets\youtube-instagram-media.ico" `
    --contents-directory $ProgramDirName `
    --add-data "assets\youtube-instagram-media.ico;assets" `
    --add-data "assets\youtube-instagram-media.png;assets" `
    --add-data "$TclDataDir;_tcl_data" `
    --add-data "$TkDataDir;_tk_data" `
    --add-data "$TclModulesDir;tcl8" `
    --add-binary "$FfmpegExe;imageio_ffmpeg\binaries" `
    --collect-all customtkinter `
    --collect-binaries imageio_ffmpeg `
    --hidden-import ctypes._layout `
    --hidden-import yt_dlp `
    "src\youtube_instagram_media_extractor\__main__.py"

$BuiltAppDir = Join-Path $DistDir $ExeBaseName
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
