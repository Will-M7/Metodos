#Requires -Version 5.1
param([string]$Destino=(Join-Path ([Environment]::GetFolderPath('UserProfile')) 'MetodosNumericos'),[switch]$Revisado)
$ErrorActionPreference='Stop'
$repository='Will-M7/Metodos'
$stage=$null
function Test-Procedencia([string]$Root,[string]$ManifestHash) {
    $path=Join-Path $Root 'sistema/manifiesto.json'
    if ((Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant() -ne $ManifestHash) { throw 'Manifiesto local modificado; no se ejecuto codigo.' }
    $manifest=Get-Content -LiteralPath $path -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($manifest.proyecto -ne 'metodos-cliente-servidor-v2') { throw 'Repositorio no reconocido.' }
    foreach ($entry in $manifest.archivos) {
        if ($entry.ruta -match '(^/|\\|:|(^|/)\.\.?(/|$))') { throw 'Ruta del manifiesto invalida' }
        $file=Join-Path $Root $entry.ruta
        if (-not (Test-Path -LiteralPath $file -PathType Leaf)) { throw ('Falta codigo: '+$entry.ruta) }
        $cursor=Get-Item -LiteralPath $file -Force
        while ($cursor -and $cursor.FullName -ne $Root) {
            if ($cursor.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'No ejecutar codigo mediante enlaces.' }
            $cursor=Get-Item -LiteralPath (Split-Path $cursor.FullName -Parent) -Force
        }
        if ((Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash.ToLowerInvariant() -ne $entry.sha256) { throw ('Codigo modificado conservado: '+$entry.ruta) }
        if ([IO.Path]::GetExtension($file) -eq '.ps1') { Unblock-File -LiteralPath $file }
    }
    foreach ($required in @('inicio.ps1','cliente/auto.ps1','cliente/instalar.ps1','cliente/comun.ps1','cliente/dependencias.ps1')) {
        if (@($manifest.archivos | Where-Object { $_.ruta -eq $required }).Count -ne 1) { throw 'Manifiesto de instalacion incompleto.' }
    }
}
try {
    if ($env:OS -ne 'Windows_NT') { throw 'Ejecutar desde PowerShell en Windows.' }
    Write-Host 'AVISO: este comando descarga y ejecuta codigo de Will-M7/Metodos. Revise inicio.ps1 y cliente/auto.ps1 antes de autorizarlo.'
    if (-not $Revisado) { throw 'Tras revisar el origen, ejecutar con -Revisado.' }
    [Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12
    $Destino=[IO.Path]::GetFullPath($Destino).TrimEnd('\','/')
    if (Test-Path -LiteralPath $Destino) {
        $originFile=Join-Path $Destino '.cliente/origen.json'
        if (-not (Test-Path -LiteralPath $originFile)) { throw 'El destino ya existe; no se sobrescribio ni ejecuto. Use otra carpeta.' }
        $origin=Get-Content -LiteralPath $originFile -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($origin.Repositorio -ne $repository -or $origin.Revision -notmatch '^[a-f0-9]{40}$') { throw 'Instalacion previa de procedencia desconocida; conservada.' }
        Test-Procedencia $Destino $origin.ManifestoSHA256
        Set-Location -LiteralPath $Destino
        & (Join-Path $Destino 'cliente/auto.ps1')
        exit $LASTEXITCODE
    }
    $commit=Invoke-RestMethod -Uri ('https://api.github.com/repos/'+$repository+'/commits/main') -Headers @{Accept='application/vnd.github+json'} -TimeoutSec 30
    $revision=[string]$commit.sha
    if ($revision -notmatch '^[a-f0-9]{40}$') { throw 'GitHub no devolvio una revision valida.' }
    $parent=Split-Path $Destino -Parent
    [void][IO.Directory]::CreateDirectory($parent)
    $stage=Join-Path $parent ('.metodos-descarga-'+[guid]::NewGuid().ToString('N'))
    [void][IO.Directory]::CreateDirectory($stage)
    $code=Join-Path $stage 'codigo'
    if (Get-Command git -ErrorAction SilentlyContinue) {
        & git -c http.sslVerify=true clone --no-checkout ('https://github.com/'+$repository+'.git') $code
        if ($LASTEXITCODE -ne 0) { throw 'Fallo git clone.' }
        & git -C $code -c advice.detachedHead=false checkout --detach $revision
        if ($LASTEXITCODE -ne 0) { throw 'No se pudo fijar la revision de GitHub.' }
        $actual=(& git -C $code rev-parse HEAD).Trim()
        if ($actual -ne $revision) { throw 'Revision descargada distinta de la solicitada.' }
    } else {
        $zip=Join-Path $stage 'repositorio.zip'
        Invoke-WebRequest -UseBasicParsing -Uri ('https://api.github.com/repos/'+$repository+'/zipball/'+$revision) -Headers @{Accept='application/vnd.github+json'} -OutFile $zip -TimeoutSec 120
        Add-Type -AssemblyName System.IO.Compression.FileSystem
        $archive=[IO.Compression.ZipFile]::OpenRead($zip)
        try {
            foreach ($entry in $archive.Entries) {
                if ($entry.FullName -match '(^/|\\|:|(^|/)\.\.?(/|$))' -or (($entry.ExternalAttributes -shr 16) -band 61440) -eq 40960) { throw 'ZIP con ruta o enlace no permitido.' }
            }
        } finally { $archive.Dispose() }
        $unzip=Join-Path $stage 'zip'
        Expand-Archive -LiteralPath $zip -DestinationPath $unzip
        $folders=@(Get-ChildItem -LiteralPath $unzip -Directory)
        if ($folders.Count -ne 1) { throw 'Estructura ZIP inesperada.' }
        Move-Item -LiteralPath $folders[0].FullName -Destination $code
    }
    # El bootstrap revisado y el de la revision fijada deben coincidir; evita mezclar versiones.
    if ((Get-FileHash -LiteralPath (Join-Path $code 'inicio.ps1')).Hash -ne (Get-FileHash -LiteralPath $PSCommandPath).Hash) { throw 'El bootstrap cambio de version; revisar la version publicada y su hash antes de continuar.' }
    $manifestHash=(Get-FileHash -LiteralPath (Join-Path $code 'sistema/manifiesto.json')).Hash.ToLowerInvariant()
    Test-Procedencia $code $manifestHash
    if (Test-Path -LiteralPath $Destino) { throw 'El destino aparecio durante la descarga; se conserva sin sobrescribir.' }
    Move-Item -LiteralPath $code -Destination $Destino
    Write-Host "Repositorio verificado en revision $revision. Destino: $Destino"
    Set-Location -LiteralPath $Destino
    & (Join-Path $Destino 'cliente/auto.ps1') -OrigenRevision $revision -OrigenManifesto $manifestHash
    exit $LASTEXITCODE
} catch { Write-Error $_ -ErrorAction Continue;exit 1 }
finally { if ($stage -and (Test-Path -LiteralPath $stage)) { Remove-Item -LiteralPath $stage -Recurse -Force } }
