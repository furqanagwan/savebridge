# Build the separately licensed ooz CLI for Halo save decompression (MSVC x64).
$ErrorActionPreference = 'Stop'
$haloRoot = Split-Path -Parent $PSScriptRoot
$haloRevision = '05038060aa68f9187ae9923b2388ca8db40e58d1'
$haloWork = Join-Path ([IO.Path]::GetTempPath()) ('savebridge-ooz-' + [guid]::NewGuid())
$haloVswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer\vswhere.exe'
$haloVs = & $haloVswhere -latest -products '*' -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
if (!$haloVs) { throw 'Visual Studio with C++ tools is required.' }
New-Item -ItemType Directory -Path $haloWork | Out-Null
git -C $haloWork init --quiet
if ($LASTEXITCODE) { throw 'git init failed' }
git -C $haloWork fetch --quiet --depth 1 https://github.com/powzix/ooz.git $haloRevision
if ($LASTEXITCODE) { throw 'ooz source download failed' }
git -C $haloWork checkout --quiet FETCH_HEAD
if ($LASTEXITCODE) { throw 'ooz source checkout failed' }
# Upstream omitted the stat declaration required by recent MSVC.
Add-Content -LiteralPath (Join-Path $haloWork 'stdafx.h') -Value '#include <sys/stat.h>'
$haloBuild = @"
@echo off
call "$haloVs\VC\Auxiliary\Build\vcvars64.bat" >nul
if errorlevel 1 exit /b 1
cd /d "$haloWork"
cl /nologo /O2 /EHsc kraken.cpp lzna.cpp bitknit.cpp /Fe:ooz.exe
"@
Set-Content -LiteralPath (Join-Path $haloWork 'build.cmd') -Value $haloBuild
& (Join-Path $haloWork 'build.cmd')
if ($LASTEXITCODE) { throw 'ooz build failed' }
$haloDest = Join-Path $haloRoot 'savebridge\_native'
New-Item -ItemType Directory -Path $haloDest -Force | Out-Null
Copy-Item -LiteralPath (Join-Path $haloWork 'ooz.exe') -Destination $haloDest
Write-Output "Built $haloDest\ooz.exe. GPL-3.0-or-later source retained at $haloWork."
