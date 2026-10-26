#Requires -Version 5.1
$ErrorActionPreference='Stop'
try {
    . (Join-Path $PSScriptRoot 'comun.ps1')
    $code=Invoke-Metodos -Modo 'generar'
    exit $code
} catch { Write-Error $_ -ErrorAction Continue;exit 1 }
