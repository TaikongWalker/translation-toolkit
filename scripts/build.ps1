#requires -Version 5.1
<#
.SYNOPSIS
    Build a translation project to PDF.

.DESCRIPTION
    Generates LaTeX metadata/glossary from project.json and terms.csv,
    compiles with XeLaTeX via latexmk, copies the PDF to dist/,
    then runs the quality checker.

.EXAMPLE
    .\scripts\build.ps1 -Project projects\my-book -Open

.EXAMPLE
    .\scripts\build.ps1 -Clean
#>
[CmdletBinding()]
param(
    [string]$Project = ".",
    [switch]$Clean,
    [switch]$Open,
    [switch]$NoCheck,
    [switch]$Strict
)

$ErrorActionPreference = "Stop"
$env:PYTHONIOENCODING = "utf-8"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$workspace = Split-Path -Parent $scriptDir

function Write-Step([string]$Message) {
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

try {
    $proj = (Resolve-Path -LiteralPath $Project).Path
} catch {
    Write-Host "[ERROR] Project path not found: $Project" -ForegroundColor Red
    exit 1
}

$mainTex = Join-Path $proj "main.tex"
$projectJson = Join-Path $proj "project.json"
if (-not (Test-Path -LiteralPath $mainTex)) {
    Write-Host "[ERROR] main.tex not found in $proj" -ForegroundColor Red
    exit 1
}
if (-not (Test-Path -LiteralPath $projectJson)) {
    Write-Host "[ERROR] project.json not found in $proj" -ForegroundColor Red
    exit 1
}

$slug = "book"
try {
    $meta = Get-Content -LiteralPath $projectJson -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($meta.slug) { $slug = [string]$meta.slug }
} catch {
    Write-Host "[WARN] Could not parse project.json; using 'book' as slug." -ForegroundColor Yellow
}

if ($Clean) {
    Write-Step "Clean build directory"
    $buildDir = Join-Path $proj "build"
    if (Test-Path -LiteralPath $buildDir) {
        Remove-Item -LiteralPath $buildDir -Recurse -Force
    }
}

Write-Step "Prepare metadata and glossary"
$previousEap = $ErrorActionPreference
$ErrorActionPreference = "Continue"
& python (Join-Path $scriptDir "prepare.py") --project $proj 2>&1 | Out-Host
$prepareCode = $LASTEXITCODE
$ErrorActionPreference = $previousEap
if ($prepareCode -ne 0) {
    Write-Host "[ERROR] prepare.py failed." -ForegroundColor Red
    exit $prepareCode
}

Write-Step "Generate bibliography and index"
$previousEap = $ErrorActionPreference
$ErrorActionPreference = "Continue"
& python (Join-Path $scriptDir "backmatter.py") --project $proj 2>&1 | Out-Host
$backmatterCode = $LASTEXITCODE
$ErrorActionPreference = $previousEap
if ($backmatterCode -ne 0) {
    Write-Host "[WARN] backmatter.py failed; bibliography/index may be stale." -ForegroundColor Yellow
}

$buildDir = Join-Path $proj "build"
if (-not (Test-Path -LiteralPath $buildDir)) {
    New-Item -ItemType Directory -Path $buildDir | Out-Null
}

Write-Step "Compile with XeLaTeX (latexmk)"
Push-Location -LiteralPath $proj
$previousEap = $ErrorActionPreference
try {
    # latexmk writes progress/warnings to stderr; treat them as normal output.
    $ErrorActionPreference = "Continue"
    & latexmk -xelatex -interaction=nonstopmode -halt-on-error -file-line-error -synctex=1 -outdir=build main.tex 2>&1 | Out-Host
    $latexCode = $LASTEXITCODE
} finally {
    $ErrorActionPreference = $previousEap
    Pop-Location
}

$pdfSource = Join-Path $proj "build\main.pdf"
if ($latexCode -ne 0 -or -not (Test-Path -LiteralPath $pdfSource)) {
    Write-Host "[ERROR] LaTeX compilation failed (exit $latexCode)." -ForegroundColor Red
    $log = Join-Path $proj "build\main.log"
    if (Test-Path -LiteralPath $log) {
        Write-Host "--- last 60 lines of main.log ---" -ForegroundColor Yellow
        Get-Content -LiteralPath $log -Tail 60 -Encoding UTF8
    }
    exit 1
}

Write-Step "Copy PDF to dist"
$distDir = Join-Path $proj "dist"
if (-not (Test-Path -LiteralPath $distDir)) {
    New-Item -ItemType Directory -Path $distDir | Out-Null
}
$pdfTarget = Join-Path $distDir ("{0}.pdf" -f $slug)
try {
    Copy-Item -LiteralPath $pdfSource -Destination $pdfTarget -Force -ErrorAction Stop
} catch {
    # PDF 正被阅读器占用时，写一个带时间戳的副本，避免构建失败
    $stamp = Get-Date -Format "yyyyMMdd-HHmm"
    $pdfTarget = Join-Path $distDir ("{0}-{1}.pdf" -f $slug, $stamp)
    Copy-Item -LiteralPath $pdfSource -Destination $pdfTarget -Force
    Write-Host "[WARN] dist PDF is locked (open in a viewer); wrote $pdfTarget instead." -ForegroundColor Yellow
}

$pages = "?"
$logPath = Join-Path $proj "build\main.log"
if (Test-Path -LiteralPath $logPath) {
    $match = Select-String -LiteralPath $logPath -Pattern "Output written on .*?\((\d+) pages?" | Select-Object -Last 1
    if ($match) { $pages = $match.Matches[0].Groups[1].Value }
}
Write-Host "[OK] PDF: $pdfTarget ($pages pages)" -ForegroundColor Green

if (-not $NoCheck) {
    Write-Step "Quality check"
    $previousEap = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    & python (Join-Path $scriptDir "check.py") --project $proj 2>&1 | Out-Host
    $checkCode = $LASTEXITCODE
    $ErrorActionPreference = $previousEap
    if ($checkCode -ne 0) {
        Write-Host "[WARN] Quality check reported errors. Review the output above." -ForegroundColor Yellow
        if ($Strict) {
            exit $checkCode
        }
    }
}

if ($Open) {
    Start-Process -FilePath $pdfTarget
}

exit 0
