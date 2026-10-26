#Requires -Version 5.1
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$script:Repo=Split-Path $PSScriptRoot -Parent

function Quote-Native([string]$Value) {
    if ($Value.Contains([char]0)) { throw 'Argumento invalido' }
    $quoted=[regex]::Replace($Value,'(\\*)"','$1$1\"')
    $quoted=[regex]::Replace($quoted,'(\\+)$','$1$1')
    return '"'+$quoted+'"'
}

function Get-Native([string]$Name) {
    $found=Get-Command $Name -ErrorAction SilentlyContinue
    if ($found) { return $found.Source }
    $fallback=Join-Path $env:WINDIR ('System32/OpenSSH/'+$Name+'.exe')
    if (Test-Path -LiteralPath $fallback) { return $fallback }
    throw "Falta $Name. Ejecutar instalar.ps1."
}

function Get-Tailscale {
    $found=Get-Command tailscale -ErrorAction SilentlyContinue
    if ($found) { return $found.Source }
    $candidate=Join-Path $env:ProgramFiles 'Tailscale/tailscale.exe'
    if (Test-Path -LiteralPath $candidate) { return $candidate }
    return $null
}

function Start-Native([string]$File,[string[]]$Arguments) {
    $info=New-Object Diagnostics.ProcessStartInfo
    $info.FileName=$File
    $info.Arguments=($Arguments | ForEach-Object { Quote-Native $_ }) -join ' '
    $info.UseShellExecute=$false
    $info.CreateNoWindow=$true
    $info.RedirectStandardInput=$true
    $info.RedirectStandardOutput=$true
    $info.RedirectStandardError=$true
    $info.StandardOutputEncoding=New-Object Text.UTF8Encoding($false)
    $process=New-Object Diagnostics.Process
    $process.StartInfo=$info
    [void]$process.Start()
    return $process
}

function Send-Frame($Process,$Frame) {
    $Process.StandardInput.WriteLine(($Frame | ConvertTo-Json -Compress -Depth 8))
    $Process.StandardInput.Flush()
}

function Read-Frame($Process) {
    $line=$Process.StandardOutput.ReadLine()
    if ($null -eq $line) { throw 'Conexion cerrada: servidor apagado, conexion interrumpida o acceso SSH rechazado.' }
    if ($line.Length -gt 131072) { throw 'Trama remota demasiado grande' }
    return $line | ConvertFrom-Json
}

function Get-LocalFiles([string]$Mode) {
    $extensions=@('.pdf','.xlsx','.xlsm','.m','.txt','.md','.csv','.png','.jpg','.jpeg')
    $files=New-Object Collections.Generic.List[object]
    $folders=@('entrada')
    if ($Mode -eq 'revisar') { $folders+= 'resultados' }
    foreach ($folder in $folders) {
        $base=Join-Path $script:Repo $folder
        if (Test-Path -LiteralPath $base) {
            foreach ($item in Get-ChildItem -LiteralPath $base -File -Recurse -Force) {
                $relative=$item.FullName.Substring($script:Repo.Length+1).Replace('\','/')
                $cursor=$item
                $linked=$false
                while ($cursor -and $cursor.FullName -ne $script:Repo) {
                    if ($cursor.Attributes -band [IO.FileAttributes]::ReparsePoint) { $linked=$true;break }
                    $cursor=Get-Item -LiteralPath (Split-Path $cursor.FullName -Parent) -Force
                }
                if (-not $linked -and $item.Name -ne '.gitkeep' -and $extensions -contains $item.Extension.ToLowerInvariant()) {
                    $files.Add(@{Path=$item.FullName;Remote=$relative;Length=$item.Length})
                }
            }
        }
    }
    foreach ($item in Get-ChildItem -LiteralPath $script:Repo -File) {
        if ($item.Name -notin @('AGENTS.md','README.md','requirements.txt') -and $extensions -contains $item.Extension.ToLowerInvariant() -and -not ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
            $files.Add(@{Path=$item.FullName;Remote=('entrada/raiz/'+$item.Name);Length=$item.Length})
        }
    }
    if ($files.Count -eq 0) { throw 'No hay archivos academicos. Colocarlos en entrada/.' }
    $sum=0L;foreach ($item in $files) {$sum+=$item.Length}
    if ($files.Count -gt 100 -or $sum -gt 100MB) { throw 'Limite: 100 archivos y 100 MiB por trabajo.' }
    return $files.ToArray()
}

function Send-File($Process,$File) {
    $hash=(Get-FileHash -LiteralPath $File.Path -Algorithm SHA256).Hash.ToLowerInvariant()
    Send-Frame $Process @{tipo='archivo';ruta=$File.Remote;bytes=$File.Length;sha256=$hash}
    $stream=[IO.File]::OpenRead($File.Path)
    try {
        $buffer=New-Object byte[] 49152
        while (($count=$stream.Read($buffer,0,$buffer.Length)) -gt 0) {
            Send-Frame $Process @{tipo='datos';base64=[Convert]::ToBase64String($buffer,0,$count)}
        }
    } finally { $stream.Dispose() }
    Send-Frame $Process @{tipo='fin_archivo'}
}

function Receive-File($Process,$Header,[string]$Folder) {
    $relative=[string]$Header.ruta
    if ($relative -match '(^/|\\|:|(^|/)\.\.?(/|$)|[\x00-\x1f<>"|?*])' -or $relative -match '(^|/)(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(\.|/|$)' -or $relative -match '(^|/)\.' -or $relative -match '[ .](/|$)') { throw 'Ruta remota no permitida' }
    if ([IO.Path]::GetExtension($relative).ToLowerInvariant() -notin @('.xlsx','.m','.txt','.png')) { throw 'Entregable no permitido' }
    $target=[IO.Path]::GetFullPath((Join-Path $Folder $relative))
    if (-not $target.StartsWith($Folder+[IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase)) { throw 'Ruta fuera de resultados' }
    $size=[long]$Header.bytes
    if ($size -lt 0 -or $size -gt 100MB) { throw 'Tamano remoto no permitido' }
    [void][IO.Directory]::CreateDirectory((Split-Path $target -Parent))
    $stream=[IO.File]::Open($target,[IO.FileMode]::CreateNew)
    $received=0L
    try {
        while ($received -lt $size) {
            $frame=Read-Frame $Process
            if ($frame.tipo -ne 'datos') { throw 'Transferencia incompleta' }
            $bytes=[Convert]::FromBase64String($frame.base64)
            if ($bytes.Length -eq 0 -or $bytes.Length -gt 49152 -or $received+$bytes.Length -gt $size) { throw 'Tamano de bloque invalido' }
            $stream.Write($bytes,0,$bytes.Length);$received+=$bytes.Length
        }
    } finally { $stream.Dispose() }
    if ((Read-Frame $Process).tipo -ne 'fin_archivo') { throw 'Archivo incompleto' }
    if ((Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash.ToLowerInvariant() -ne $Header.sha256) { Remove-Item -LiteralPath $target -Force;throw 'Hash del entregable incorrecto' }
}

function Invoke-Metodos {
    param([ValidateSet('revisar','respuestas','generar')][string]$Modo,[switch]$Comprobar)
    $configPath=Join-Path $script:Repo '.cliente/config.json'
    if (-not (Test-Path -LiteralPath $configPath)) { throw 'Ejecutar instalar.ps1 para configurar el cliente.' }
    $config=Get-Content -LiteralPath $configPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($config.servidor -notmatch '^100\.(6[4-9]|[7-9][0-9]|1[01][0-9]|12[0-7])\.([0-9]{1,3})\.([0-9]{1,3})$' -or $config.usuario -notmatch '^[A-Za-z0-9_.-]+$') { throw 'Configuracion SSH privada invalida' }
    $parsed=[Net.IPAddress]::Parse($config.servidor)
    $port=[int]$config.puerto
    if ($port -lt 1024 -or $port -gt 65535) { throw 'Puerto invalido' }
    Write-Host 'SISTEMA DE METODOS NUMERICOS - LAPTOP REMOTA'
    $secure=Read-Host 'Ingrese contrasena' -AsSecureString
    $process=$null;$pointer=[IntPtr]::Zero;$download=$null;$code=1
    try {
        $arguments=@('-T','-p',[string]$port,'-i',(Join-Path $script:Repo '.cliente/id_ed25519'),'-o','IdentitiesOnly=yes','-o','BatchMode=yes','-o','ConnectTimeout=10','-o','ServerAliveInterval=15','-o','ServerAliveCountMax=2','-o','StrictHostKeyChecking=yes','-o',('UserKnownHostsFile='+(Join-Path $script:Repo '.cliente/known_hosts')),($config.usuario+'@'+$config.servidor),'metodos-v1')
        $process=Start-Native (Get-Native 'ssh') $arguments
        $errors=$process.StandardError.ReadToEndAsync()
        $pointer=[Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
        $plain=[Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
        Send-Frame $process @{v=1;operacion=$Modo;clave=$plain;comprobar=[bool]$Comprobar}
        $plain=$null
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer);$pointer=[IntPtr]::Zero
        $reply=Read-Frame $process
        if ($reply.tipo -eq 'ocupado') { Write-Host $reply.texto;return 3 }
        if ($reply.tipo -eq 'disponible' -and $Comprobar) { Write-Host 'Servidor conectado y autorizacion remota comprobada.';return 0 }
        if ($reply.tipo -ne 'listo') { throw ([string]$reply.texto) }
        $identifier=[string]$reply.trabajo
        if ($identifier -notmatch '^[a-f0-9]{32}$') { throw 'Identificador de trabajo invalido' }
        foreach ($file in Get-LocalFiles $Modo) { Send-File $process $file }
        Send-Frame $process @{tipo='fin_envio'}
        $total=0L;$count=0;$hasResult=$false
        while ($true) {
            $reply=Read-Frame $process
            switch ($reply.tipo) {
                'progreso' { if ($Modo -ne 'respuestas') { Write-Host $reply.texto } }
                'salida' { Write-Host -NoNewline $reply.texto }
                'resultado' { Write-Host $reply.texto;$code=[int]$reply.codigo;$hasResult=$true }
                'archivo' {
                    if ($Modo -ne 'generar') { throw 'El servidor intento enviar archivos en modo de terminal' }
                    $total+=[long]$reply.bytes;$count++
                    if ($total -gt 100MB -or $count -gt 100) { throw 'Entregables exceden limites' }
                    if (-not $download) {
                        $download=Join-Path $script:Repo ('resultados/incompleto_'+$identifier)
                        if (Test-Path -LiteralPath $download) { throw 'Destino de descarga ya existe' }
                        $base=Join-Path $script:Repo 'resultados'
                        if ((Test-Path -LiteralPath $base) -and ((Get-Item -LiteralPath $base).Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw 'resultados no puede ser un enlace' }
                        [void][IO.Directory]::CreateDirectory($download)
                        $download=[IO.Path]::GetFullPath($download)
                    }
                    Receive-File $process $reply $download
                }
                'error' { throw ([string]$reply.texto) }
                'fin' {
                    if (-not $hasResult -or $reply.trabajo -ne $identifier) { throw 'Respuesta remota incompleta' }
                    Send-Frame $process @{tipo='recibido';trabajo=$identifier}
                    if ((Read-Frame $process).tipo -ne 'cerrado') { throw 'No se confirmo limpieza temporal remota' }
                    if ($download) {
                        $destination=Join-Path $script:Repo ('resultados/trabajo_'+$identifier)
                        if (Test-Path -LiteralPath $destination) { throw 'Destino final ya existe' }
                        Move-Item -LiteralPath $download -Destination $destination
                        Write-Host "Entregables recibidos y comprobados: $destination"
                    }
                    return $code
                }
                default { throw 'Respuesta remota desconocida' }
            }
        }
    } catch {
        if ($download) { Write-Host "DESCARGA INCOMPLETA conservada en: $download" }
        if ($process -and $process.HasExited -and $errors) {
            $detail=$errors.GetAwaiter().GetResult()
            if ($detail) { Write-Host $detail }
        }
        throw
    } finally {
        if ($pointer -ne [IntPtr]::Zero) { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer) }
        $secure.Dispose();$plain=$null
        if ($process) {
            $process.StandardInput.Close()
            if (-not $process.WaitForExit(5000)) { $process.Kill() }
            $process.Dispose()
        }
    }
}
