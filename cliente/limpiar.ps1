#Requires -Version 5.1
$ErrorActionPreference='Stop'
$root=Split-Path $PSScriptRoot -Parent
try {
    if (Test-Path -LiteralPath (Join-Path $root '.servidor.local')) { throw 'Esta copia prepara un servidor. limpiar.ps1 es exclusivamente para clientes; no se elimino nada.' }
    $helper=Join-Path ([IO.Path]::GetTempPath()) ('mn_limpieza_'+[guid]::NewGuid().ToString('N')+'.ps1')
    Copy-Item -LiteralPath (Join-Path $root 'sistema/desinstalar.ps1') -Destination $helper
    try { & $helper -Raiz $root } finally { Remove-Item -LiteralPath $helper -Force -ErrorAction SilentlyContinue }
    exit 0
} catch { Write-Error $_ -ErrorAction Continue;exit 1 }
