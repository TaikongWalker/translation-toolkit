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

.EXAMPLE
    .\scripts\build.ps1 -Json
    # stdout 只有一行 JSON，便于 agent 解析
#>
[CmdletBinding()]
param(
    [string]$Project = ".",
    [switch]$Clean,
    [switch]$Open,
    [switch]$NoCheck,
    [switch]$Strict,
    [switch]$Json
)

$ErrorActionPreference = "Stop"
$env:PYTHONIOENCODING = "utf-8"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$workspace = Split-Path -Parent $scriptDir

function Write-Step([string]$Message) {
    if ($Json) { return }
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Say([string]$Message, [string]$Color = "White") {
    if (-not $Json) { Write-Host $Message -ForegroundColor $Color }
}

function Show-Output {
    param([Parameter(ValueFromPipeline = $true)]$Line)
    process {
        if (-not $Json) { Write-Host $Line }
    }
}

function Fail([string]$Message) {
    if ($Json) {
        [ordered]@{ ok = $false; exit_code = 1; error = $Message } |
            ConvertTo-Json -Compress
    } else {
        Write-Host "[ERROR] $Message" -ForegroundColor Red
    }
    exit 1
}

try {
    $proj = (Resolve-Path -LiteralPath $Project).Path
} catch {
    Fail "Project path not found: $Project"
}

$mainTex = Join-Path $proj "main.tex"
$projectJson = Join-Path $proj "project.json"
if (-not (Test-Path -LiteralPath $mainTex)) {
    Fail "main.tex not found in $proj"
}
if (-not (Test-Path -LiteralPath $projectJson)) {
    Fail "project.json not found in $proj"
}

$slug = "book"
try {
    $meta = Get-Content -LiteralPath $projectJson -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($meta.slug) { $slug = [string]$meta.slug }
} catch {
    Say "[WARN] Could not parse project.json; using 'book' as slug." "Yellow"
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
if ($Json) {
    & python (Join-Path $scriptDir "prepare.py") --project $proj 2>&1 | Out-Null
} else {
    & python (Join-Path $scriptDir "prepare.py") --project $proj 2>&1 | Show-Output
}
$prepareCode = $LASTEXITCODE
$ErrorActionPreference = $previousEap
if ($prepareCode -ne 0) {
    Fail "prepare.py failed (exit $prepareCode)"
}

Write-Step "Generate bibliography and index"
$previousEap = $ErrorActionPreference
$ErrorActionPreference = "Continue"
if ($Json) {
    & python (Join-Path $scriptDir "backmatter.py") --project $proj 2>&1 | Out-Null
} else {
    & python (Join-Path $scriptDir "backmatter.py") --project $proj 2>&1 | Show-Output
}
$backmatterCode = $LASTEXITCODE
$ErrorActionPreference = $previousEap
if ($backmatterCode -ne 0) {
    Say "[WARN] backmatter.py failed; bibliography/index may be stale." "Yellow"
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
    if ($Json) {
        & latexmk -xelatex -interaction=nonstopmode -halt-on-error -file-line-error -synctex=1 -outdir=build main.tex 2>&1 | Out-Null
    } else {
        & latexmk -xelatex -interaction=nonstopmode -halt-on-error -file-line-error -synctex=1 -outdir=build main.tex 2>&1 | Show-Output
    }
    $latexCode = $LASTEXITCODE
} finally {
    $ErrorActionPreference = $previousEap
    Pop-Location
}

$pdfSource = Join-Path $proj "build\main.pdf"
if ($latexCode -ne 0 -or -not (Test-Path -LiteralPath $pdfSource)) {
    $log = Join-Path $proj "build\main.log"
    if ($Json) {
        $tail = @()
        if (Test-Path -LiteralPath $log) {
            $tail = @(Get-Content -LiteralPath $log -Tail 20 -Encoding UTF8)
        }
        [ordered]@{
            ok = $false
            exit_code = 1
            error = "LaTeX compilation failed (exit $latexCode)"
            log_tail = $tail
        } | ConvertTo-Json -Depth 4 -Compress
    } else {
        Write-Host "[ERROR] LaTeX compilation failed (exit $latexCode)." -ForegroundColor Red
        if (Test-Path -LiteralPath $log) {
            Write-Host "--- last 60 lines of main.log ---" -ForegroundColor Yellow
            Get-Content -LiteralPath $log -Tail 60 -Encoding UTF8
        }
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
    Say "[WARN] dist PDF is locked (open in a viewer); wrote $pdfTarget instead." "Yellow"
}

$pages = "?"
$logPath = Join-Path $proj "build\main.log"
if (Test-Path -LiteralPath $logPath) {
    $match = Select-String -LiteralPath $logPath -Pattern "Output written on .*?\((\d+) pages?" | Select-Object -Last 1
    if ($match) { $pages = $match.Matches[0].Groups[1].Value }
}
Say "[OK] PDF: $pdfTarget ($pages pages)" "Green"

$checkResult = $null
$checkCode = 0
if (-not $NoCheck) {
    Write-Step "Quality check"
    $previousEap = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    if ($Json) {
        $checkRaw = & python (Join-Path $scriptDir "check.py") --project $proj --json 2>$null | Out-String
        $checkCode = $LASTEXITCODE
        try {
            $checkResult = $checkRaw | ConvertFrom-Json
        } catch {
            $checkResult = $null
        }
    } else {
        & python (Join-Path $scriptDir "check.py") --project $proj 2>&1 | Show-Output
        $checkCode = $LASTEXITCODE
    }
    $ErrorActionPreference = $previousEap
    if ($checkCode -ne 0) {
        Say "[WARN] Quality check reported errors. Review the output above." "Yellow"
    }
}

$finalExit = 0
if ($Strict -and $checkCode -ne 0) {
    $finalExit = $checkCode
}

if ($Json) {
    $pageValue = $null
    if ($pages -match '^\d+$') { $pageValue = [int]$pages }
    $checkSummary = $null
    if ($checkResult) {
        $checkSummary = [ordered]@{
            ok = $checkResult.ok
            error = $checkResult.summary.error
            warn = $checkResult.summary.warn
            info = $checkResult.summary.info
        }
    } else {
        $checkSummary = [ordered]@{
            ok = ($checkCode -eq 0)
            error = $null
            warn = $null
            info = $null
        }
    }
    [ordered]@{
        ok = ($finalExit -eq 0)
        exit_code = $finalExit
        pdf = $pdfTarget
        pages = $pageValue
        check = $checkSummary
    } | ConvertTo-Json -Depth 5 -Compress
}

if ($Open) {
    Start-Process -FilePath $pdfTarget
}

exit $finalExit
