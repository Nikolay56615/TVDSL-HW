param([string]$Compiler = "gcc")

$ErrorActionPreference = "Stop"
$cc = (Get-Command $Compiler -ErrorAction Stop).Source
$tools = Join-Path $PSScriptRoot ".tools"
New-Item -ItemType Directory -Force -Path $tools | Out-Null

function Get-VerifiedArchive($Url, $File, $Hash) {
    if (!(Test-Path -LiteralPath $File) -or (Get-FileHash -LiteralPath $File).Hash -ne $Hash) {
        Invoke-WebRequest -UseBasicParsing -Uri $Url -OutFile $File
    }
    if ((Get-FileHash -LiteralPath $File).Hash -ne $Hash) {
        throw "SHA256 mismatch for $File"
    }
}

$commit = "e21106ff7e58afe79275b3ca10179556afa97aa2"
$spinArchive = Join-Path $tools "spin-source.zip"
$bisonArchive = Join-Path $tools "bison.zip"
Get-VerifiedArchive "https://codeload.github.com/nimble-code/Spin/zip/$commit" $spinArchive "82457C2F3D72096603DD52627D340550A6A6E36BBBA9F5C10592D0B02FF09203"
Get-VerifiedArchive "https://github.com/lexxmark/winflexbison/releases/download/v2.5.25/win_flex_bison-2.5.25.zip" $bisonArchive "8D324B62BE33604B2C45AD1DD34AB93D722534448F55A16CA7292DE32B6AC135"
Expand-Archive -LiteralPath $spinArchive -DestinationPath $tools -Force
Expand-Archive -LiteralPath $bisonArchive -DestinationPath (Join-Path $tools "bison") -Force

Push-Location (Join-Path $tools "Spin-$commit/Src")
try {
    & (Join-Path $tools "bison/win_bison.exe") -d -o y.tab.c --defines=y.tab.h spin.y
    if ($LASTEXITCODE -ne 0) { throw "Bison failed" }
    $sourceFiles = (Get-ChildItem -File -Filter "*.c").Name
    $temporarySpin = Join-Path $tools "spin-new.exe"
    & $cc -O2 -DPC -o $temporarySpin @sourceFiles
    if ($LASTEXITCODE -ne 0) { throw "GCC failed" }
    & $temporarySpin -V
    if ($LASTEXITCODE -ne 0) { throw "Spin could not start" }
    Move-Item -LiteralPath $temporarySpin -Destination (Join-Path $tools "spin.exe") -Force
}
finally {
    Pop-Location
}
Write-Output "Spin is ready. Run: python -m HW5 check"
