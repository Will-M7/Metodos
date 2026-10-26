#Requires -Version 5.1
param([string]$DirectorioPrivado,[string]$ClavePublica,[int]$Puerto=2222,[switch]$ActivarSSH,[switch]$RevisarReferencias)
$ErrorActionPreference='Stop'
$root=Split-Path $PSScriptRoot -Parent
try {
    if ($env:OS -ne 'Windows_NT') { throw 'En Ubuntu usar instalar_servidor.sh.' }
    $python=Get-Command py -ErrorAction SilentlyContinue
    $prefix=@('-3')
    if (-not $python) { $python=Get-Command python -ErrorAction SilentlyContinue;$prefix=@() }
    if (-not $python) {
        if (-not (Get-Command winget -ErrorAction SilentlyContinue)) { throw 'Instalar Python 3.10+ desde python.org y volver a ejecutar. No se modificaron servicios.' }
        & winget install --exact --id Python.Python.3.12 --source winget --accept-source-agreements --accept-package-agreements
        if ($LASTEXITCODE -ne 0) { throw 'Instalacion Python incompleta' }
        throw 'Python instalado. Abrir una terminal nueva y ejecutar nuevamente este instalador.'
    }
    if (-not (Get-Command octave -ErrorAction SilentlyContinue) -and -not (Get-Command octave-cli -ErrorAction SilentlyContinue) -and -not $env:METODOS_OCTAVE) { Write-Host 'Verificar/instalar GNU Octave desde https://octave.org/download y anadir mingw64/bin al PATH. Se informara pendiente si falta.' }
    if (-not (Get-Command codex -ErrorAction SilentlyContinue)) {
        if (Get-Command npm -ErrorAction SilentlyContinue) {
            & npm install -g '@openai/codex'
            if ($LASTEXITCODE -ne 0) { throw 'Instalacion Codex incompleta' }
        } else { throw 'Instalar Node.js oficial y Codex CLI en esta laptop; luego ejecutar codex login.' }
    }
    & codex login status
    if ($LASTEXITCODE -ne 0) { & codex login;if ($LASTEXITCODE -ne 0) { throw 'Falta autenticar Codex en la laptop.' } }
    . (Join-Path $root 'cliente/comun.ps1')
    $tail=Get-Tailscale
    $sshMissing=(-not (Get-Command sshd -ErrorAction SilentlyContinue) -and -not (Test-Path "$env:WINDIR/System32/OpenSSH/sshd.exe"))
    $tailMissing=-not $tail
    if ($sshMissing -or $tailMissing) {
        & (Join-Path $root 'cliente/dependencias.ps1') -Ssh -SshServidor:$sshMissing -Tailscale:$tailMissing
        if ($LASTEXITCODE -ne 0) { throw 'Dependencias SSH/Tailscale incompletas' }
    }
    $tail=Get-Tailscale
    if (-not $tail) { throw 'Tailscale no disponible' }
    $status=& $tail status --json | ConvertFrom-Json
    if ($status.BackendState -ne 'Running') { & $tail up;if ($LASTEXITCODE -ne 0) { throw 'Autorizar laptop en Tailscale.' } }
    $arguments=@('-B','-m','servidor.preparar','--instalar-paquetes','--probar-codex','--migrar-referencias','--puerto',[string]$Puerto)
    if ($DirectorioPrivado) { $arguments+=@('--home',$DirectorioPrivado) }
    if ($ClavePublica) { $arguments+=@('--clave-publica',[IO.Path]::GetFullPath($ClavePublica)) }
    if ($ActivarSSH) { $arguments+='--activar-ssh' }
    if ($RevisarReferencias) { $arguments+='--revisar-referencias' }
    Push-Location $root
    try { & $python.Source @prefix @arguments;exit $LASTEXITCODE } finally { Pop-Location }
} catch { Write-Error $_ -ErrorAction Continue;exit 1 }
