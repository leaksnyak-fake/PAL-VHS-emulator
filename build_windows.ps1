param([switch]$CliOnly, [switch]$Offline, [string]$OutputDirectory = 'dist\GStreamer')
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if (Test-Path -LiteralPath '.tools\native\bin\cargo.exe') {
    $env:PATH = (Join-Path $PSScriptRoot '.tools\native\bin') + ';' +
        (Join-Path $PSScriptRoot '.tools\binutils\mingw64\bin') + ';' +
        (Join-Path $PSScriptRoot '.tools\native\lib\rustlib\x86_64-pc-windows-gnu\bin\self-contained') +
        ';C:\Program Files\Git\mingw64\bin;' + $env:PATH
    $env:CARGO_HOME = Join-Path $PSScriptRoot '.tools\cargo'
}
if (-not $CliOnly -and (Test-Path -LiteralPath '.tools\gstreamer\build-env.ps1')) {
    . '.\.tools\gstreamer\build-env.ps1'
}
$cargoArgs = @('build','--release','--locked')
if ($CliOnly) { $cargoArgs += '--no-default-features' }
if ($Offline) { $cargoArgs += '--offline' }
& cargo @cargoArgs
if ($LASTEXITCODE -ne 0) { throw 'Rust build failed' }
New-Item -ItemType Directory -Force -Path $OutputDirectory | Out-Null
Copy-Item -LiteralPath 'target\release\pal-vhs.exe' -Destination (Join-Path $OutputDirectory 'PAL-VHS.exe') -Force
Copy-Item -LiteralPath 'README.md' -Destination (Join-Path $OutputDirectory 'README.md') -Force
New-Item -ItemType Directory -Force -Path (Join-Path $OutputDirectory 'docs') | Out-Null
foreach ($document in @('VALIDATION.md','GSTREAMER_PREVIEW.md')) {
    Copy-Item -LiteralPath (Join-Path 'docs' $document) -Destination (Join-Path $OutputDirectory 'docs') -Force
}
if (-not $CliOnly -and $env:PAL_VHS_GSTREAMER_ROOT) {
    $runtimeRoot = $env:PAL_VHS_GSTREAMER_ROOT
    Get-ChildItem -LiteralPath (Join-Path $runtimeRoot 'bin') -Filter '*.dll' -File | ForEach-Object {
        Copy-Item -LiteralPath $_.FullName -Destination $OutputDirectory -Force
    }
    foreach ($relative in @('lib\gstreamer-1.0','libexec\gstreamer-1.0','share\wheel-notices','share\licenses')) {
        $sourcePath = Join-Path $runtimeRoot $relative
        if ($relative -eq 'lib\gstreamer-1.0' -and (Test-Path -LiteralPath (Join-Path $runtimeRoot 'lib\gstreamer-1.0-preview'))) {
            $sourcePath = Join-Path $runtimeRoot 'lib\gstreamer-1.0-preview'
        }
        if (Test-Path -LiteralPath $sourcePath) {
            $destinationPath = Join-Path $OutputDirectory $relative
            New-Item -ItemType Directory -Force -Path $destinationPath | Out-Null
            Get-ChildItem -LiteralPath $sourcePath -Force | ForEach-Object {
                Copy-Item -LiteralPath $_.FullName -Destination $destinationPath -Recurse -Force
            }
        }
    }
}
Write-Output ('Built ' + (Join-Path $OutputDirectory 'PAL-VHS.exe') + '. FFmpeg/FFprobe are needed for export.')
