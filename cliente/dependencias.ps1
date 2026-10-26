#Requires -Version 5.1
param([switch]$Ssh,[switch]$Tailscale,[switch]$SshServidor)
$ErrorActionPreference='Stop'
$principal=New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    $arguments='-NoProfile -File "'+$PSCommandPath+'"'
    if ($Ssh) {$arguments+=' -Ssh'}
    if ($Tailscale) {$arguments+=' -Tailscale'}
    if ($SshServidor) {$arguments+=' -SshServidor'}
    $process=Start-Process powershell -Verb RunAs -ArgumentList $arguments -PassThru -Wait
    exit $process.ExitCode
}
if ($Ssh -and (Get-WindowsCapability -Online -Name 'OpenSSH.Client~~~~0.0.1.0').State -ne 'Installed') {
    Add-WindowsCapability -Online -Name 'OpenSSH.Client~~~~0.0.1.0' | Out-Null
}
if ($SshServidor -and (Get-WindowsCapability -Online -Name 'OpenSSH.Server~~~~0.0.1.0').State -ne 'Installed') {
    Add-WindowsCapability -Online -Name 'OpenSSH.Server~~~~0.0.1.0' | Out-Null
    # No iniciar el servicio sshd global ni abrir su puerto. Se usara otra instancia privada.
}
if ($Tailscale -and -not (Test-Path "$env:ProgramFiles/Tailscale/tailscale.exe")) {
    [Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12
    $installer=Join-Path ([IO.Path]::GetTempPath()) ('tailscale_'+[guid]::NewGuid().ToString('N')+'.exe')
    try {
        Invoke-WebRequest -Uri 'https://pkgs.tailscale.com/stable/tailscale-setup-latest.exe' -OutFile $installer -UseBasicParsing
        $signature=Get-AuthenticodeSignature -LiteralPath $installer
        if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch '(?i)(^|,\s*)O=Tailscale(?: Inc\.?)?(,|$)') { throw 'Instalador Tailscale sin firma valida del editor esperado; no ejecutado.' }
        $installed=Start-Process -FilePath $installer -PassThru -Wait
        if ($installed.ExitCode -notin @(0,3010)) { throw 'La instalacion de Tailscale no finalizo correctamente.' }
    } finally { Remove-Item -LiteralPath $installer -Force -ErrorAction SilentlyContinue }
}
