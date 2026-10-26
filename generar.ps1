#Requires -Version 5.1
& (Join-Path $PSScriptRoot 'cliente/generar.ps1') @args
exit $LASTEXITCODE
