#Requires -Version 5.1
param([string]$Servidor='100.116.157.0',[string]$OrigenRevision,[string]$OrigenManifesto)
$ErrorActionPreference='Stop'
try {
    if ($env:OS -ne 'Windows_NT') { throw 'Este instalador requiere Windows 10/11.' }
    . (Join-Path $PSScriptRoot 'comun.ps1')
    # Habilitar scripts locales sólo si se trata de la política predeterminada del usuario.
    # No alterar LocalMachine, GPO ni una política explícita AllSigned del propietario.
    if ((Get-ExecutionPolicy -Scope CurrentUser) -eq 'Undefined' -and (Get-ExecutionPolicy -Scope MachinePolicy) -eq 'Undefined' -and (Get-ExecutionPolicy -Scope UserPolicy) -eq 'Undefined' -and (Get-ExecutionPolicy -Scope LocalMachine) -in @('Undefined','Restricted')) {
        Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned -Force
    }

    # El instalador previo mantiene instalación oficial, UAC, ACL e idempotencia de las claves.
    & (Join-Path $PSScriptRoot 'instalar.ps1') -SoloPreparar -PreparacionAutomatica
    if ($LASTEXITCODE -ne 0) { throw 'Preparacion local incompleta.' }
    $folder=Join-Path $script:Repo '.cliente'
    function Save-Metadata([string]$Name,$Data) {
        if ($Name -notin @('origen.json','enrolamiento.json')) { throw 'Metadato no permitido' }
        $target=Join-Path $folder $Name
        $Data | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $target -Encoding UTF8
        $ownerPath=Join-Path $folder 'propiedad.json'
        $owner=Get-Content -LiteralPath $ownerPath -Raw | ConvertFrom-Json
        if ($owner.proyecto -ne 'metodos-cliente-v2') { throw 'Propietario del cliente desconocido' }
        $entries=@($owner.archivos | Where-Object { $_.ruta -ne ('.cliente/'+$Name) })
        $entries+=@{ruta=('.cliente/'+$Name);sha256=(Get-FileHash -LiteralPath $target).Hash.ToLowerInvariant()}
        @{proyecto=$owner.proyecto;archivos=$entries} | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $ownerPath -Encoding UTF8
    }

    if ($OrigenRevision -or $OrigenManifesto) {
        if ($OrigenRevision -notmatch '^[a-f0-9]{40}$' -or $OrigenManifesto -notmatch '^[a-f0-9]{64}$') { throw 'Procedencia de descarga invalida' }
        Save-Metadata 'origen.json' @{Repositorio='Will-M7/Metodos';Revision=$OrigenRevision;ManifestoSHA256=$OrigenManifesto}
    }
    $tail=Get-Tailscale
    $local=& $tail status --json | ConvertFrom-Json
    if ($LASTEXITCODE -ne 0 -or $local.BackendState -ne 'Running') { throw 'Tailscale no esta autenticado.' }
    $peer=& $tail whois --json $Servidor | ConvertFrom-Json
    if ($LASTEXITCODE -ne 0) { throw 'La laptop no aparece en la interfaz autenticada de Tailscale.' }
    if ([string]$peer.UserProfile.ID -ne [string]$local.Self.UserID -or [string]$peer.Node.User -ne [string]$local.Self.UserID) { throw 'La laptop pertenece a otro usuario Tailscale.' }
    if ($peer.Node.PSObject.Properties['Tags'] -and $null -ne $peer.Node.Tags -and @($peer.Node.Tags).Count -gt 0) { throw 'No se admite un servidor etiquetado en lugar de la laptop personal.' }
    $addresses=@($peer.Node.Addresses | ForEach-Object { ($_ -split '/')[0] })
    if ($addresses -notcontains $Servidor) { throw 'La identidad Tailscale no corresponde a la IP esperada.' }
    $dns=([string]$peer.Node.Name).TrimEnd('.')
    if ($dns -notmatch '^[a-z0-9-]+\.[a-z0-9.-]+\.ts\.net$') { throw 'Nombre HTTPS no verificado por Tailscale.' }
    # No se envian cabeceras Tailscale-* ni contrasena. Serve obtiene la identidad del canal real.
    [Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12
    $url='https://'+$dns+'/metodos-alta/enrolar'
    $public=(Get-Content -LiteralPath (Join-Path $folder 'id_ed25519.pub') -Raw).Trim()
    $body=@{clave_publica=$public} | ConvertTo-Json -Compress
    $reply=Invoke-RestMethod -Uri $url -Method Post -ContentType 'application/json; charset=utf-8' -Body ([Text.Encoding]::UTF8.GetBytes($body)) -TimeoutSec 30
    if ($reply.servidor -ne $Servidor -or [int]$reply.puerto -ne 2222 -or $reply.huella -notmatch '^SHA256:[A-Za-z0-9+/]+$' -or $reply.usuario -notmatch '^[A-Za-z0-9_.-]+$') { throw 'Respuesta de alta inconsistente con la laptop.' }
    $keygen=Start-Native (Get-Native 'ssh-keygen') @('-lf',(Join-Path $folder 'id_ed25519.pub'),'-E','sha256')
    $keyError=$keygen.StandardError.ReadToEndAsync();$fingerprint=$keygen.StandardOutput.ReadToEnd();$keygen.WaitForExit()
    if ($keygen.ExitCode -ne 0 -or ($fingerprint -split '\s+') -notcontains $reply.clave_cliente) { throw 'El servidor no confirmo la clave publica de este Windows.' }
    $keygen.Dispose()
    Save-Metadata 'enrolamiento.json' @{url=$url;servidor=$Servidor;huella=$reply.huella;clave_cliente=$reply.clave_cliente}
    & (Join-Path $PSScriptRoot 'instalar.ps1') -Servidor $Servidor -Usuario $reply.usuario -Puerto 2222 -Huella $reply.huella -SinPrueba -PreparacionAutomatica
    if ($LASTEXITCODE -ne 0) { throw 'Fallo la comprobacion de huella SSH o la configuracion local.' }
    # Un solo probe: contrasena oculta, verificada en Ubuntu, sin Codex ni gasto de tokens.
    $code=Invoke-Metodos -Modo respuestas -Comprobar
    if ($code -ne 0) { throw 'Servidor ocupado o autorizacion incompleta; reintentar cliente/auto.ps1.' }
    Write-Host 'Cliente instalado y autorizado. Colocar ejercicios en entrada/.'
    Write-Host '.\revisar.ps1   .\respuestas.ps1   .\generar.ps1   .\limpiar.ps1'
    exit 0
} catch { Write-Error $_ -ErrorAction Continue;exit 1 }
