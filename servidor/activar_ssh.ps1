#Requires -Version 5.1
param([string]$Ejecutable,[string]$Configuracion,[string]$Direccion,[int]$Puerto=2222)
$ErrorActionPreference='Stop'
$principal=New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    $arguments='-NoProfile -File "'+$PSCommandPath+'" -Ejecutable "'+$Ejecutable+'" -Configuracion "'+$Configuracion+'" -Direccion '+$Direccion+' -Puerto '+$Puerto
    $process=Start-Process powershell -Verb RunAs -ArgumentList $arguments -PassThru -Wait
    exit $process.ExitCode
}
& $Ejecutable -t -f $Configuracion
if ($LASTEXITCODE -ne 0) { throw 'Configuracion SSH invalida' }
$name='MetodosNumericosSSH'
$binary='"'+$Ejecutable+'" -f "'+$Configuracion+'"'
$existing=Get-CimInstance Win32_Service -Filter "Name='$name'" -ErrorAction SilentlyContinue
if ($existing -and $existing.PathName -ne $binary) { throw 'Existe servicio con otro propietario/configuracion; no se modifico' }
if (-not $existing) { New-Service -Name $name -BinaryPathName $binary -StartupType Automatic | Out-Null }
$rule=Get-NetFirewallRule -Name 'MetodosNumericosSSH-Tailscale' -ErrorAction SilentlyContinue
if (-not $rule) { New-NetFirewallRule -Name 'MetodosNumericosSSH-Tailscale' -DisplayName 'Metodos SSH privado' -Direction Inbound -Action Allow -Protocol TCP -LocalAddress $Direccion -LocalPort $Puerto -RemoteAddress '100.64.0.0/10' | Out-Null }
Start-Service $name
Write-Host 'Servicio SSH propio activo, enlazado a la IP privada de Tailscale.'
