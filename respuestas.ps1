#Requires -Version 5.1
& (Join-Path $PSScriptRoot 'cliente/respuestas.ps1') @args
exit $LASTEXITCODE
