#requires -Version 5.1
<#
.SYNOPSIS
    Create a new translation project from _template.

.EXAMPLE
    .\scripts\new-project.ps1 -Name my-book -Title "书名" -Source "D:\books\book.epub"

.EXAMPLE
    .\scripts\new-project.ps1 -Name my-essay -Title "我的文章" -SourceLang en
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Name,

    [string]$Title = "",
    [string]$Subtitle = "",
    [string]$Author = "",
    [string]$Translator = "",
    [string]$SourceLang = "en",
    [string]$Year = (Get-Date -Format "yyyy"),
    [string]$Source = ""
)

$ErrorActionPreference = "Stop"
$env:PYTHONIOENCODING = "utf-8"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$workspace = Split-Path -Parent $scriptDir
$template = Join-Path $workspace "_template"
$target = Join-Path (Join-Path $workspace "projects") $Name

function Invoke-PythonStep {
    param(
        [string]$Label,
        [string[]]$PythonArgs
    )
    Write-Host "==> $Label" -ForegroundColor Cyan
    $old = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    & python @PythonArgs 2>&1 | Out-Host
    $code = $LASTEXITCODE
    $ErrorActionPreference = $old
    if ($code -ne 0) {
        Write-Host "[ERROR] $Label failed (exit $code)." -ForegroundColor Red
    }
    return $code
}

if (-not (Test-Path -LiteralPath $template)) {
    Write-Host "[ERROR] Template not found: $template" -ForegroundColor Red
    exit 1
}
if (Test-Path -LiteralPath $target) {
    Write-Host "[ERROR] Project already exists: $target" -ForegroundColor Red
    exit 1
}

Write-Host "==> Create project: $target" -ForegroundColor Cyan
New-Item -ItemType Directory -Path (Split-Path -Parent $target) -Force | Out-Null
Copy-Item -LiteralPath $template -Destination $target -Recurse

# 清理模板的构建产物
foreach ($sub in @("build", "dist")) {
    $path = Join-Path $target $sub
    if (Test-Path -LiteralPath $path) {
        Remove-Item -LiteralPath $path -Recurse -Force
    }
}
New-Item -ItemType Directory -Path (Join-Path $target "build") -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $target "dist") -Force | Out-Null

# 清掉模板示例内容：章节、术语、进度
Get-ChildItem -LiteralPath (Join-Path $target "chapters") -Filter "*.tex" -ErrorAction SilentlyContinue |
    Remove-Item -Force
Get-ChildItem -LiteralPath (Join-Path $target "figures") -File -ErrorAction SilentlyContinue |
    Remove-Item -Force
Set-Content -LiteralPath (Join-Path $target "glossary\terms.csv") `
    -Value "source,target,category,status,notes,forbidden,first_seen" -Encoding UTF8
Set-Content -LiteralPath (Join-Path $target "notes\progress.csv") `
    -Value "unit,file,status,zh_chars,todo,updated,notes" -Encoding UTF8

$code = Invoke-PythonStep -Label "Update project.json" -PythonArgs @(
    (Join-Path $scriptDir "init_project.py"),
    "--dir", $target, "--slug", $Name, "--title", $Title,
    "--subtitle", $Subtitle, "--author", $Author,
    "--translator", $Translator, "--source-lang", $SourceLang,
    "--year", $Year
)
if ($code -ne 0) { exit $code }

if ($Source) {
    if (-not (Test-Path -LiteralPath $Source)) {
        Write-Host "[ERROR] Source file not found: $Source" -ForegroundColor Red
        exit 1
    }
    $ext = [IO.Path]::GetExtension($Source).ToLower()
    if ($ext -eq ".epub") {
        $code = Invoke-PythonStep -Label "Extract EPUB" -PythonArgs @(
            (Join-Path $scriptDir "epub_extract.py"),
            "--epub", $Source, "--out", (Join-Path $target "source"), "--clean"
        )
        if ($code -eq 0) {
            $code = Invoke-PythonStep -Label "Scaffold chapter files" -PythonArgs @(
                (Join-Path $scriptDir "scaffold.py"), "--project", $target
            )
        }
    } else {
        Write-Host "[INFO] Non-EPUB source: copying to source/ (follow docs/01-工作流.md stage 0)." -ForegroundColor Yellow
        Copy-Item -LiteralPath $Source -Destination (Join-Path $target "source") -Force
    }
}

$code = Invoke-PythonStep -Label "Prepare LaTeX metadata" -PythonArgs @(
    (Join-Path $scriptDir "prepare.py"), "--project", $target
)
if ($code -ne 0) { exit $code }

Write-Host ""
Write-Host "[OK] Project created: $target" -ForegroundColor Green
Write-Host "Next:"
Write-Host "  1. Fill notes/context.md (stage 1)"
Write-Host "  2. Build the glossary (stage 2): python scripts/term_candidates.py --project `"$target`""
Write-Host "  3. Pilot translation (stage 3), then chapters (stage 4)"
Write-Host "  4. Build PDF: scripts/build.ps1 -Project `"$target`" -Open"
