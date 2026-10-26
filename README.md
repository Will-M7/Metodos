# Métodos Numéricos por SSH privado

Un repositorio, cuatro comandos de cliente y un único motor en la laptop. Se conservan los módulos `src/` del sistema anterior: extracción, Codex, verificación, Excel y Octave. `servidor/worker.py` los despacha; `cliente/` sólo usa PowerShell y OpenSSH. No hay HTTP, base de datos ni interfaz propia.

La copia de la laptop y la de la otra PC cumplen roles distintos. **Nunca instalar los motores en el cliente.** Los scripts de la raíz conservan los nombres anteriores y redirigen a `cliente/`.

## Alta inicial (confianza entre los dos equipos)

La primera conexión necesita enrolar una clave pública y comprobar la huella de la laptop. No es posible autorizar un equipo nuevo ni adivinar la dirección de la laptop sólo con `git clone`.

1. En la PC Windows cliente:

```powershell
git clone <URL_DEL_REPOSITORIO> MetodosNumericos
cd MetodosNumericos
.\instalar.ps1 -SoloPreparar
```

Instala OpenSSH Client mediante Windows Capability si falta y Tailscale desde su distribución oficial, comprobando Authenticode y editor. Pide elevación normal cuando hace falta y autorización oficial de Tailscale. Genera una clave ED25519 específica de esta copia, protegida mediante ACL. Mostrar/copiar **sólo** `.cliente/id_ed25519.pub` a la laptop. Nunca enviar la clave sin `.pub`.

2. En la laptop Windows, preparar Codex autenticado para el mismo usuario Windows que recibirá los trabajos; instalar/verificar GNU Octave. Ejecutar:

```powershell
.\servidor\instalar_servidor.ps1 -ClavePublica C:\ruta\cliente.pub -ActivarSSH -RevisarReferencias
```

El instalador verifica/instala Python y las bibliotecas en un venv privado, verifica Octave, instala Codex si dispone de npm y comprueba su autenticación. Si falta Node/Octave informa el requisito oficial. Prepara OpenSSH Server y Tailscale cuando faltan. No inicia el SSH global: crea únicamente su instancia `MetodosNumericosSSH`, enlazada a la IP **Tailscale** en el puerto 2222, con regla de firewall propia y comando forzado. No abre puertos del router ni publica SSH en Internet. Si un componente falla, muestra disponibilidad pendiente y no declara el servidor listo.

En el alta privada, **introducir la contraseña inicial acordada** y repetirla; no hay contraseña ni verificador predeterminado en el código público. Introducir la misma contraseña al operar desde el cliente. Se almacena sólo un verificador PBKDF2 con sal aleatoria en el directorio privado de la laptop.

El directorio privado predeterminado es `%LOCALAPPDATA%\metodos-servidor` (Windows) o `~/.local/share/metodos-servidor` (Ubuntu); puede cambiarse con `-DirectorioPrivado` / `--home`. Debe estar fuera del repositorio. Contiene configuración, referencias, perfiles efectivos, historial de las reglas antiguas, caché y trabajos. El instalador copia y comprueba los hashes del lote completo antes de retirar los originales del repositorio. Ante conflictos conserva los originales y no sobrescribe destinos distintos. Los archivos académicos existentes permanecen excluidos de Git.

En Ubuntu:

```bash
# Python 3.10+, python3-venv, Octave, OpenSSH Server, Tailscale y Codex autenticado.
./servidor/instalar_servidor.sh --clave-publica /ruta/cliente.pub --activar-ssh --migrar-referencias --revisar-referencias
```

El script verifica los programas del SO y muestra lo que falta; instala las bibliotecas en su venv privado. La instancia SSH es un servicio **propio de usuario**, enlazado a Tailscale. Se necesita systemd de usuario y el directorio de separación de privilegios de OpenSSH que prepara su paquete. Para mantenerlo accesible después de cerrar sesión, un administrador puede habilitar `loginctl enable-linger USUARIO`. No se modifican servicios SSH ajenos. Si la distribución no permite sshd sin privilegios, la activación queda pendiente: configurar esta misma instancia privada con el administrador, sin abrir el servicio global.

La laptop muestra IP privada, usuario, puerto y huella `SHA256:...`. Debe permanecer encendida, sin suspensión y conectada a Tailscale. Autorizar en la política de la red privada únicamente los dispositivos/personas deseados.

3. Volver al cliente y completar:

```powershell
.\instalar.ps1 -Servidor 100.100.10.20 -Usuario miusuario -Huella 'SHA256:HUELLA_MOSTRADA_EN_LA_LAPTOP'
```

El instalador compara la huella obtenida con la indicada, configura `known_hosts`, solicita la contraseña y prueba la autorización **en el servidor**, sin iniciar IA ni resolver un ejercicio. Repetirlo reutiliza las dependencias y la clave que ya funcionan. Una laptop apagada, fuera de Tailscale, ocupada o no enrolada deja la configuración para reintentar y comunica el fallo; no se da por instalada una conexión no comprobada. Si una política institucional bloquea scripts, aplicar la política del administrador; no se cambia la configuración global de ejecución.

## Uso cotidiano

Colocar archivos en `entrada/` de la PC cliente. También se reconocen PDF/Excel/M/TXT/MD/CSV/PNG/JPG académicos en la raíz; al revisar se incluyen entregables de `resultados/`. No se envían referencias, perfiles, claves ni carpetas del sistema.

```powershell
.\revisar.ps1       # evaluación rigurosa por terminal
.\respuestas.ps1    # sólo respuestas finales numeradas
.\generar.ps1       # Excel, scripts, salida real, gráficas/capturas disponibles
.\limpiar.ps1       # desinstalación exclusivamente local del cliente
```

Cada una de las tres operaciones solicita contraseña oculta y la envía por stdin **dentro de SSH**, nunca en argumentos ni historial. La laptop verifica antes de recibir los archivos o invocar Codex. SSH usa clave específica, huella fijada, sin PTY ni reenvíos. El comando forzado acepta sólo `metodos-v1`; el protocolo sólo permite revisar/respuestas/generar. No ofrece una consola PowerShell ni SFTP de libre acceso. Las transferencias se realizan por el canal cifrado de SSH, en bloques con SHA256, no mediante un servidor adicional.

Un lock del SO permite un solo trabajo; si está ocupado se rechaza antes de subir archivos o gastar IA. Cada trabajo tiene UUID y carpeta propia. Los trabajos recibidos nunca alimentan las referencias centrales. Después de confirmar la recepción se elimina el temporal. Ante desconexión, EOF o tiempo agotado también se limpia; durante el cálculo se comprueba la conexión y se termina el árbol de procesos. No hay reanudación de trabajos: reintentar inicia otro UUID. Límites: 100 archivos / 100 MiB por transferencia y una hora por trabajo.

En generación los resultados se reciben en `resultados/trabajo_UUID/`, sin sobrescribir entregas anteriores. Una descarga interrumpida queda como `incompleto_UUID`, señalada en terminal; no equivale a un trabajo completo. Revisión/respuestas no escriben informes en el cliente. Los archivos transferidos y su contenido no se ejecutan en la PC cliente.

## Fidelidad académica con revisión crítica

Las 26 reglas históricas se conservan en el respaldo privado, **sin presumir que estén validadas**. Los 21 archivos originales se conservan hasta que su migración haya sido comprobada. Las plantillas públicas de perfil no distribuyen esas reglas privadas. En esta sesión no se han certificado de nuevo los 21 documentos: falta Codex real accesible para completar la auditoría.

La revisión inicial (`-RevisarReferencias` / `--revisar-referencias`) y la comprobación previa a resolver inspeccionan cada archivo nuevo/modificado. Codex separa ejercicios, enunciado, procedimiento, fórmulas, ubicación y origen docente/estudiante/desconocido. Clasifica cada ejercicio:

- `VALIDADA`: procedimiento/resultados comprobados por Codex, aritmética Python y ejecución real de Octave.
- `INCORRECTA`: errores con ubicación, fórmula, corrección y discrepancia numérica demostrable; se conserva intacta y sólo aporta formato independiente de sus cálculos.
- `PENDIENTE`: falta evidencia, hay ilegibilidad o falló alguna comprobación; sólo puede aportar formato.

Sólo ejercicios `VALIDADA` alimentan reglas matemáticas. Las fórmulas/resultados no verificados se excluyen del contexto de resolución; se utiliza un extracto auditado con fuente y hash, no imágenes completas con regiones sin revisar. Las reglas matemáticas antiguas o de fuentes cambiadas/eliminadas se invalidan **antes** de llamar a Codex, incluso si la nueva llamada falla. El progreso se guarda por archivo, no se repiten revisiones sin cambios y no se confirma una fórmula por aparecer repetida. Para reevaluar explícitamente una referencia pendiente tras corregir evidencia/dependencias, el administrador puede retirar sólo esa entrada de la caché privada y volver a solicitar revisión.

Se respeta método explícito > ejemplo válido del docente > trabajo anterior validado > regla confirmada > convencional identificado. La exactitud matemática prevalece sobre copiar errores. Un conflicto sin resolver deja pendiente esa pregunta.

## Entregables y límites conservados del motor

Excel monocromo, una pregunta por hoja, desarrollo e iteraciones con fórmulas. Se contrasta un subconjunto explícito de fórmulas y se guardan valores cacheados comprobados; openpyxl no equivale a ejecutar Microsoft Excel. Plantillas simples `entrada/plantilla.xlsx` se conservan; las que contienen objetos no preservables quedan pendientes y no se destruyen. Cada ejercicio tiene script Octave sencillo y salida real. Las gráficas proceden de Octave.

Por SSH el trabajador no asume acceso a una sesión gráfica Windows: conserva scripts/salidas y marca capturas pendientes. El mecanismo previo de captura real se mantiene para un escritorio interactivo utilizable. No se simulan ventanas. Sin evidencias obligatorias, el trabajo se entrega parcial y se identifica como incompleto. La revisión final de archivos generados vuelve a consultar Codex. La IA interpreta la evidencia; las comprobaciones numéricas no certifican por sí solas toda esa interpretación.

Codex se ejecuta sólo en la laptop mediante `codex exec --sandbox read-only`, autenticación existente, stdin y esquema estructurado. Los scripts Octave recibidos/generados pasan un filtro matemático preventivo; ese filtro no sustituye un sandbox del SO. Usar cuentas, dispositivos y materiales académicos de confianza. La contraseña es una barrera casual; el acceso real depende también de claves SSH y autorización privada.

## Limpieza

`limpiar.ps1` nunca conecta con la laptop. Usa el manifiesto SHA256 de código y el manifiesto de propiedad de `.cliente/`; elimina únicamente rutas permitidas con contenido coincidente. Los archivos modificados, enlaces y archivos ajenos se conservan. Los manifiestos quedan como constancia. Preserva entrada, resultados, perfiles, PDF/Excel/M/capturas del usuario y cualquier ruta no registrada. Conserva las herramientas compartidas (OpenSSH/Tailscale/Git). Una marca `.servidor.local` impide limpiar una copia usada como servidor. No altera `.git`, historial, registros externos ni datos remotos.

## Descarga inicial sin Git

Desde PowerShell nativo, sustituyendo propietario y repositorio reales:

```powershell
$zip=Join-Path $env:TEMP 'metodos-cliente.zip'
Invoke-WebRequest 'https://github.com/PROPIETARIO/REPOSITORIO/archive/refs/heads/main.zip' -OutFile $zip
Expand-Archive -LiteralPath $zip -DestinationPath .
cd .\REPOSITORIO-main
.\instalar.ps1 -SoloPreparar
```

Usar el archivo ZIP del repositorio publicado, no una copia de la carpeta privada de la laptop. El repositorio de Git debe excluir `.cliente/`, `.mn_cache/`, referencias y trabajos como indica `.gitignore`.

## Validación

En la laptop con dependencias:

```powershell
python -B -m unittest discover -s tests -v
```

Se conservan las pruebas matemáticas anteriores y se adaptan las de autenticación/limpieza al nuevo rol. Las pruebas del protocolo usan pipes reales y verifican autenticación, rechazo, ocupado, aislamiento, hashes, caída de conexión, cancelación de procesos, migración y transferencia de Excel/M con Octave real. La IA se sustituye explícitamente donde no está accesible; pipes locales no demuestran cifrado SSH ni funcionamiento en Windows.

Pruebas externas opt-in: `METODOS_VM_LIMPIA=1` en una VM Windows con autorización interactiva para instalar; `METODOS_PROBAR_REMOTO=1` y `METODOS_CLAVE_PRUEBA` en un entorno privado para comprobar un cliente enrolado contra la laptop real. Esas pruebas no se ejecutan automáticamente sobre un equipo de uso diario. Capturas y recálculo Excel requieren validación en sus aplicaciones nativas.

Documentación técnica consultada: [OpenSSH y opciones de comando forzado](https://man.openbsd.org/sshd), [OpenSSH oficial de Windows](https://learn.microsoft.com/en-us/windows-server/administration/openssh/openssh_install_firstuse), [Tailscale Windows](https://tailscale.com/docs/install/windows), [Codex no interactivo](https://developers.openai.com/codex/noninteractive/).

Resultado de esta sesión Linux: **40 pruebas aprobadas y 7 omitidas**. Octave, generación/lectura Excel, protocolo en pipes, autenticación del servidor, cancelación de procesos, migración verificada y el error real de Lagrange fueron comprobados. `codex exec` real falló al inicializar su cliente por el sistema de archivos de sólo lectura; no hay IP Tailscale utilizable ni OpenSSH Server aquí. Pendientes: Windows limpio/PowerShell, SSH/Tailscale entre equipos, laptop apagada, capturas, Excel nativo y auditoría completa de los 21 materiales con Codex real. Los originales permanecen intactos hasta ejecutar la migración en una ubicación privada persistente de la laptop.
