#Requires -Version 5.1
& (Join-Path $PSScriptRoot 'cliente/limpiar.ps1') @args
exit $LASTEXITCODE
