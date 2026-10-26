#Requires -Version 5.1
& (Join-Path $PSScriptRoot 'cliente/instalar.ps1') @args
exit $LASTEXITCODE
