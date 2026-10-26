#Requires -Version 5.1
& (Join-Path $PSScriptRoot 'cliente/revisar.ps1') @args
exit $LASTEXITCODE
