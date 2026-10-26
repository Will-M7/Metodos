param([Parameter(Mandatory=$true)][string]$Raiz)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$rootPath = [IO.Path]::GetFullPath($Raiz).TrimEnd([IO.Path]::DirectorySeparatorChar, [IO.Path]::AltDirectorySeparatorChar)
if (Test-Path -LiteralPath (Join-Path $rootPath '.servidor.local')) { throw 'No limpiar una copia configurada como servidor.' }
$manifestPath = Join-Path $rootPath 'sistema/manifiesto.json'
$manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
if ($manifest.proyecto -ne 'metodos-cliente-servidor-v2') { throw 'Manifiesto no reconocido; no se elimino nada.' }
$separator = [IO.Path]::DirectorySeparatorChar
$deleted = 0
$entries=@($manifest.archivos)
$dynamic=Join-Path $rootPath '.cliente/propiedad.json'
if (Test-Path -LiteralPath $dynamic) {
    $local=Get-Content -LiteralPath $dynamic -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($local.proyecto -eq 'metodos-cliente-v2') {
        foreach ($item in $local.archivos) {
            if ($item.ruta -match '^\.cliente/(config\.json|origen\.json|enrolamiento\.json|known_hosts|id_ed25519(?:\.pub)?)$') { $entries+=$item }
        }
    }
}
foreach ($entry in $entries) {
    $relative = [string]$entry.ruta
    # Independiente del manifiesto: datos academicos, perfil, .git y rutas ajenas son intocables.
    $allowed = $relative -match '^(inicio\.ps1|instalar\.ps1|revisar\.ps1|respuestas\.ps1|generar\.ps1|limpiar\.ps1|requirements\.txt|README\.md|AGENTS\.md|\.gitignore|\.gitattributes|src/[a-z_]+\.py|sistema/[a-z_]+\.ps1|cliente/[a-z_]+\.ps1|servidor/[a-z_]+\.(py|ps1|sh)|\.cliente/(config\.json|origen\.json|enrolamiento\.json|known_hosts|id_ed25519(?:\.pub)?)|tests/[a-z_]+\.py)$'
    if (-not $allowed -or $relative.Contains('..')) { Write-Host "CONSERVADO (ruta no autorizada): $relative"; continue }
    $target = [IO.Path]::GetFullPath((Join-Path $rootPath $relative))
    if (-not $target.StartsWith($rootPath + $separator, [StringComparison]::OrdinalIgnoreCase)) { continue }
    $cursor = $target
    $link = $false
    while ($cursor -and $cursor.Length -ge $rootPath.Length) {
        if (Test-Path -LiteralPath $cursor) {
            if ((Get-Item -LiteralPath $cursor -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) { $link = $true; break }
        }
        if ($cursor -eq $rootPath) { break }
        $cursor = [IO.Path]::GetDirectoryName($cursor)
    }
    if ($link) { Write-Host "CONSERVADO (enlace): $relative"; continue }
    if (-not (Test-Path -LiteralPath $target -PathType Leaf)) { continue }
    $hash = (Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($hash -ne $entry.sha256) { Write-Host "CONSERVADO (modificado/propietario ambiguo): $relative"; continue }
    Remove-Item -LiteralPath $target -Force
    $deleted++
}
# No se borran carpetas recursivamente, dependencias globales, venv ajenos ni datos/cache academicos.
foreach ($name in @('src', 'sistema', 'tests', 'cliente', 'servidor')) {
    $dir = Join-Path $rootPath $name
    if ((Test-Path -LiteralPath $dir -PathType Container) -and -not (Get-ChildItem -LiteralPath $dir -Force | Select-Object -First 1)) {
        Remove-Item -LiteralPath $dir
    }
}
Write-Host "Limpieza selectiva finalizada: $deleted componentes eliminados. Datos academicos, servidor y archivos ambiguos conservados. No se desinstalan herramientas compartidas."
