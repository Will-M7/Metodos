#Requires -Version 5.1
param([string]$Servidor,[string]$Usuario,[int]$Puerto=2222,[string]$Huella,[switch]$SoloPreparar)
$ErrorActionPreference='Stop'
try {
    if ($env:OS -ne 'Windows_NT') { throw 'El cliente requiere Windows 10/11 y PowerShell 5.1 o posterior.' }
    . (Join-Path $PSScriptRoot 'comun.ps1')
    Write-Host ('Windows '+[Environment]::OSVersion.Version+'; PowerShell '+$PSVersionTable.PSVersion)
    $ssh=Get-Command ssh -ErrorAction SilentlyContinue
    $tail=Get-Tailscale
    $helper=Join-Path $PSScriptRoot 'dependencias.ps1'
    $sshMissing=(-not $ssh -and -not (Test-Path "$env:WINDIR/System32/OpenSSH/ssh.exe"))
    $tailMissing=-not $tail
    if ($sshMissing -or $tailMissing) {
        & $helper -Ssh:$sshMissing -Tailscale:$tailMissing
        if ($LASTEXITCODE -ne 0) { throw 'Dependencias incompletas; revisar autorizacion de administrador.' }
    }
    $tail=Get-Tailscale
    if (-not $tail) { throw 'Tailscale no disponible tras la instalacion.' }
    $status=& $tail status --json | ConvertFrom-Json
    if ($status.BackendState -ne 'Running') {
        Write-Host 'Autorizar este dispositivo en Tailscale mediante el enlace oficial mostrado.'
        & $tail up
        if ($LASTEXITCODE -ne 0) { throw 'Falta completar la autorizacion de Tailscale.' }
    }
    $folder=Join-Path $script:Repo '.cliente'
    $owner=Join-Path $folder 'propiedad.json'
    if ((Test-Path -LiteralPath $folder) -and -not (Test-Path -LiteralPath $owner)) { throw '.cliente ya existe sin propietario verificable; no se sobrescribio.' }
    [void][IO.Directory]::CreateDirectory($folder)
    if (-not (Test-Path -LiteralPath $owner)) { @{proyecto='metodos-cliente-v2';archivos=@()} | ConvertTo-Json | Set-Content -LiteralPath $owner -Encoding UTF8 }
    $who=[Security.Principal.WindowsIdentity]::GetCurrent().Name
    & icacls $folder /inheritance:r /grant:r ($who+':(OI)(CI)F') 'SYSTEM:(OI)(CI)F' | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'No se pudieron proteger los archivos privados del cliente.' }
    $key=Join-Path $folder 'id_ed25519'
    if (-not (Test-Path -LiteralPath $key)) {
        $process=Start-Native (Get-Native 'ssh-keygen') @('-t','ed25519','-f',$key,'-N','','-C','metodos-cliente')
        $output=$process.StandardOutput.ReadToEnd();$errorText=$process.StandardError.ReadToEnd();$process.WaitForExit()
        if ($process.ExitCode -ne 0) { throw ('No se genero clave SSH: '+$errorText) }
        $process.Dispose()
    }
    Write-Host 'Enrolar SOLO esta clave publica en la laptop (nunca copiar la clave privada):'
    Write-Host (Get-Content -LiteralPath ($key+'.pub') -Raw)
    if (-not $SoloPreparar) {
        $config=Join-Path $folder 'config.json'
        $old=if (Test-Path -LiteralPath $config) { Get-Content -LiteralPath $config -Raw | ConvertFrom-Json } else { $null }
        if (-not $Servidor) { $Servidor=if ($old) {$old.servidor} else {Read-Host 'IP Tailscale de la laptop (100.x)'} }
        if (-not $Usuario) { $Usuario=if ($old) {$old.usuario} else {Read-Host 'Usuario SSH de la laptop'} }
        if (-not $Huella) { $Huella=if ($old) {$old.huella} else {Read-Host 'Huella SHA256:... mostrada en la laptop'} }
        $ip=[Net.IPAddress]::Parse($Servidor).GetAddressBytes()
        if ($ip.Length -ne 4 -or $ip[0] -ne 100 -or $ip[1] -lt 64 -or $ip[1] -gt 127 -or $Usuario -notmatch '^[A-Za-z0-9_.-]+$' -or $Puerto -lt 1024 -or $Puerto -gt 65535 -or $Huella -notmatch '^SHA256:[A-Za-z0-9+/]+$') { throw 'IP privada, usuario, puerto o huella invalidos' }
        $known=Join-Path $folder 'known_hosts'
        $scan=Start-Native (Get-Native 'ssh-keyscan') @('-T','10','-t','ed25519','-p',[string]$Puerto,$Servidor)
        $scanError=$scan.StandardError.ReadToEndAsync();$lines=$scan.StandardOutput.ReadToEnd();$scan.WaitForExit()
        if ($scan.ExitCode -ne 0 -or -not $lines.Trim()) { throw 'Laptop no accesible por SSH privado; comprobar encendido, Tailscale y servicio.' }
        $temp=Join-Path $folder 'known_hosts.tmp'
        try {
            [IO.File]::WriteAllText($temp,$lines,(New-Object Text.UTF8Encoding($false)))
            $verify=Start-Native (Get-Native 'ssh-keygen') @('-lf',$temp,'-E','sha256')
            $fingerprint=$verify.StandardOutput.ReadToEnd();$verifyError=$verify.StandardError.ReadToEndAsync();$verify.WaitForExit()
            if ($verify.ExitCode -ne 0 -or ($fingerprint -split '\s+') -notcontains $Huella) { throw 'La huella SSH no coincide con la laptop. No se establecio confianza.' }
            Move-Item -LiteralPath $temp -Destination $known -Force
        } finally { Remove-Item -LiteralPath $temp -Force -ErrorAction SilentlyContinue }
        @{version=2;servidor=$Servidor;usuario=$Usuario;puerto=$Puerto;huella=$Huella} | ConvertTo-Json | Set-Content -LiteralPath $config -Encoding UTF8
    }
    $entries=@()
    foreach ($name in @('id_ed25519','id_ed25519.pub','known_hosts','config.json')) {
        $file=Join-Path $folder $name
        if (Test-Path -LiteralPath $file) { $entries+=@{ruta=('.cliente/'+$name);sha256=(Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash.ToLowerInvariant()} }
    }
    @{proyecto='metodos-cliente-v2';archivos=$entries} | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $owner -Encoding UTF8
    if ($SoloPreparar) { Write-Host 'Transporte preparado. Tras enrolar la clave publica, ejecutar instalar.ps1 con los datos de la laptop.';exit 0 }
    $code=Invoke-Metodos -Modo respuestas -Comprobar
    if ($code -ne 0) { throw 'Servidor ocupado o comunicacion sin confirmar. Configuracion conservada para reintentar.' }
    Write-Host 'Instalacion del cliente terminada. No se instalaron Python, Codex, Octave ni Excel.'
    exit 0
} catch { Write-Error $_ -ErrorAction Continue;exit 1 }
