param([Parameter(Mandatory=$true)][string]$Octave,
      [Parameter(Mandatory=$true)][string]$Script,
      [Parameter(Mandatory=$true)][string]$Destino)
$ErrorActionPreference = 'Stop'
if (-not [Environment]::UserInteractive -or $env:SSH_CONNECTION) { throw 'No hay escritorio interactivo utilizable.' }
Add-Type -AssemblyName System.Drawing
Add-Type @'
using System;
using System.Runtime.InteropServices;
public class VentanaOctave {
 [StructLayout(LayoutKind.Sequential)] public struct Rect { public int Left, Top, Right, Bottom; }
 [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out Rect rect);
 [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
 [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
 [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int cmd);
}
'@
$octaveProcess = $null
try {
    $ruta = $Script.Replace('\', '/').Replace("'", "''")
    $expression = 'echo on; source(''' + $ruta + '''); disp(''EJECUCION FINALIZADA'');'
    $octaveProcess = Start-Process -FilePath $Octave -ArgumentList @('--no-init-file', '--no-site-file', '--gui', '--persist', '--eval', ('"' + $expression + '"')) -PassThru
    $handle = [IntPtr]::Zero
    for ($i=0; $i -lt 30; $i++) {
        Start-Sleep -Milliseconds 500
        $octaveProcess.Refresh()
        if ($octaveProcess.HasExited) { throw 'La instancia de Octave terminó o reutilizó otra ventana; no se capturó.' }
        $handle = $octaveProcess.MainWindowHandle
        if ($handle -ne [IntPtr]::Zero) { break }
    }
    if ($handle -eq [IntPtr]::Zero) { throw 'No se encontró ventana propia de Octave.' }
    [void][VentanaOctave]::ShowWindow($handle, 9)
    [void][VentanaOctave]::SetForegroundWindow($handle)
    Start-Sleep -Seconds 4
    if ([VentanaOctave]::GetForegroundWindow() -ne $handle) { throw 'Octave no esta al frente; no se capturo otra ventana.' }
    $rect = New-Object VentanaOctave+Rect
    if (-not [VentanaOctave]::GetWindowRect($handle, [ref]$rect)) { throw 'No se pudo medir la ventana.' }
    $bitmap = New-Object System.Drawing.Bitmap ($rect.Right-$rect.Left), ($rect.Bottom-$rect.Top)
    $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
    try {
        $graphics.CopyFromScreen($rect.Left, $rect.Top, 0, 0, $bitmap.Size)
        $bitmap.Save($Destino, [System.Drawing.Imaging.ImageFormat]::Png)
    } finally { $graphics.Dispose(); $bitmap.Dispose() }
} finally {
    if ($octaveProcess -and -not $octaveProcess.HasExited) { [void]$octaveProcess.CloseMainWindow() }
}
