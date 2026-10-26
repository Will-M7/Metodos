# Métodos Numéricos — instalación automática y cálculo remoto

Se conserva el motor existente en `src/` y los cuatro comandos. La laptop Ubuntu `100.116.157.0` calcula mediante Codex/Octave y genera Excel; Windows sólo instala PowerShell/OpenSSH/Tailscale y transporta los trabajos. No hay API de cálculo HTTP ni interfaz propia. HTTPS privado se utiliza únicamente para dar de alta claves SSH.

## Dos comandos

**Ubuntu, una vez, en una terminal normal del propietario:**

```bash
cd /home/willian/Desarrollo/metodos && bash servidor/preparar_automatico.sh
```

El script comprueba/instala paquetes Ubuntu con apt oficial, prepara el venv y Codex (solicita su login si falta), verifica el propietario real de Tailscale y pide la contraseña de operaciones oculta en el alta privada. Conserva referencias/resultados: esta ruta automática copia y verifica, nunca retira originales. Comprueba Codex real con esquema de salida y ejecuta Octave real.

Crea solamente `metodos-ssh.service` y `metodos-alta.service` de usuario, habilita arranque, reinicia y comprueba ambas unidades. Activa `loginctl enable-linger` y verifica que Tailscaled arranque tras reinicio. SSH particular escucha sólo en la IP Tailscale, puerto 2222, con comando forzado y archivo de claves inicialmente vacío. No requiere una clave de arranque ni instala una clave temporal. El PATH de Node/Codex se conserva en la sesión no interactiva. Si hay un trabajo en curso no reinicia sus servicios.

No edita el SSH general existente ni puertos del router. Si debe instalar por primera vez el paquete OpenSSH Server, impide el arranque automático de sus unidades generales recién creadas y las deja deshabilitadas; nunca detiene unidades SSH preexistentes. No reemplaza políticas de instalación ajenas. Las fuentes Tailscale se obtienen por HTTPS oficial y los paquetes se autentican con su keyring apt; las fuentes existentes distintas se conservan.

Tailscale puede requerir la autorización oficial del dispositivo y habilitar HTTPS para la tailnet durante esta configuración única. Después no es necesario copiar claves ni visitar físicamente Ubuntu para nuevos clientes del propietario. Mantener la laptop sin suspensión y su identidad Tailscale vigente; revisar la caducidad del nodo en la consola de Tailscale antes de dejarla desatendida.

**Windows nuevo, un solo comando PowerShell, después de publicar estos cambios en `main`:**

Antes de ejecutarlo, revisar [inicio.ps1](inicio.ps1), [cliente/auto.ps1](cliente/auto.ps1) y su procedencia. El comando valida SHA256 antes de ejecutar; no utilizar `iex` con una descarga sin comprobar.

```powershell
& { $p=Join-Path $env:TEMP ('metodos-inicio-'+[guid]::NewGuid().ToString('N')+'.ps1'); try { [Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -UseBasicParsing 'https://raw.githubusercontent.com/Will-M7/Metodos/main/inicio.ps1' -OutFile $p; if ((Get-FileHash -LiteralPath $p -Algorithm SHA256).Hash -ne '827A06091742C1C550B5E7BA0753A3D98973C0E1975D57C7BCB22C4E41F723AA') { throw 'Hash del instalador incorrecto' }; Unblock-File -LiteralPath $p; Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned -Force; & $p -Revisado } finally { Remove-Item -LiteralPath $p -Force -ErrorAction SilentlyContinue } }
```

Destino predeterminado: `%USERPROFILE%\MetodosNumericos`. El bootstrap resuelve una revisión concreta mediante la API HTTPS del repositorio **Will-M7/Metodos**. Usa Git si ya existe o un ZIP oficial de esa misma revisión si falta. Valida manifiesto y hashes; no sobrescribe instalaciones ni trabajos. Una instalación previa de procedencia reconocida y código intacto se reutiliza; los destinos ajenos o modificados se conservan sin ejecutar. No actualiza versiones anteriores automáticamente. Desbloquea únicamente scripts cuyo hash ya comprobó.

`cliente/auto.ps1` reutiliza el instalador anterior, instala sólo OpenSSH Client/Tailscale si faltan y solicita elevación normal. Tailscale pide su autorización oficial una vez. Genera y protege una clave ED25519 local; únicamente envía la pública por HTTPS privado. Descubre el DNS del Ubuntu mediante **tailscale whois**, contrasta su propietario con el del Windows y obtiene la huella SSH por el canal HTTPS autenticado. Compara esa huella con SSH antes de guardar la configuración. Finalmente pide la contraseña oculta y hace un único probe en Ubuntu que no ejecuta Codex ni consume tokens.

Para permitir los cuatro scripts locales, sólo ante políticas predeterminadas Undefined/Restricted configura RemoteSigned del usuario actual. No modifica LocalMachine, GPO ni rebaja AllSigned. La política Process del comando inicial sólo dura esa terminal. Una política institucional que impida ejecutar scripts necesita autorización del administrador.

## Seguridad y revocación del alta

El backend `servidor/enrolamiento.py` escucha **únicamente en un socket Unix 0600** dentro del directorio privado 0700 del servidor. Tailscale Serve, sin Funnel, publica exclusivamente `/metodos-alta` por HTTPS privado. Se preservan las rutas de otras aplicaciones; un conflicto de ruta aborta sin reemplazarla.

Serve elimina las cabeceras de identidad que enviase un cliente y establece las reales. El backend exige HTTPS, rechaza Funnel y cabeceras repetidas, y contrasta `X-Forwarded-For` con `tailscale whois --json`: Node.StableID, Node.User, Node.Addresses y UserProfile.ID/LoginName. El propietario se deriva de Self.UserID de la interfaz local de Tailscale, no de datos del solicitante. Se rechazan otros usuarios, nodos etiquetados y dispositivos revocados. Por defecto se aceptan dispositivos personales de ese propietario que ya tienen acceso autorizado a la tailnet; puede restringirse `allowed_nodes` en el archivo privado `alta_config.json`.

Sólo se admite un JSON con `clave_publica` ED25519 de estructura SSH válida. No admite comandos ni rutas del cliente. Cada clave queda vinculada al StableID real y restringida mediante `from=` a las IP del nodo devueltas por Tailscale. Las autorizaciones se actualizan con flock, reemplazo atómico y permisos 0600. Las claves manuales antiguas fuera del bloque administrado se conservan; no se presume poder revocarlas mediante este registro.

Administración local, usando el Python privado de la laptop:

```bash
~/.local/share/metodos-servidor/venv/bin/python -B -m servidor.enrolamiento listar
~/.local/share/metodos-servidor/venv/bin/python -B -m servidor.enrolamiento revocar --nodo ID_ESTABLE
```

Una revocación elimina sus claves gestionadas y bloquea el reenrolamiento de ese dispositivo incluso con una clave nueva. No termina sesiones SSH ya abiertas. El registro y bloqueos son privados y persisten tras reinicios. La contraseña de operaciones no interviene en HTTPS: se pide sólo para el probe/operaciones por SSH y se verifica en Ubuntu. La clave privada permanece en Windows.

Referencias oficiales: [identidad de Tailscale Serve](https://tailscale.com/docs/features/tailscale-serve#identity-headers), [CLI whois](https://tailscale.com/docs/reference/tailscale-cli#whois), [implementación oficial de cabeceras del proxy](https://github.com/tailscale/tailscale/blob/main/ipn/ipnlocal/serve.go).

## Compatibilidad con la instalación anterior

Se mantienen `instalar.ps1`, `cliente/instalar.ps1`, los instaladores manuales Windows/Ubuntu, todos los módulos matemáticos y pruebas anteriores. `SinPrueba` evita una segunda prueba de contraseña durante el alta automática; `PreparacionAutomatica` omite instrucciones de copia manual de claves. Ambos parámetros existen explícitamente en el instalador.

La copia privada continúa en `%LOCALAPPDATA%\metodos-servidor` o `~/.local/share/metodos-servidor`; `--home` permite otra ubicación externa al repositorio. No se distribuyen referencias, perfiles efectivos, caché, credenciales ni trabajos privados a Windows.

## Uso cotidiano

Colocar archivos en `entrada/` de la PC cliente. También se reconocen PDF/Excel/M/TXT/MD/CSV/PNG/JPG académicos en la raíz; al revisar se incluyen entregables de `resultados/`. No se envían referencias, perfiles, claves ni carpetas del sistema.

```powershell
.\revisar.ps1       # evaluación rigurosa por terminal
.\respuestas.ps1    # sólo respuestas finales numeradas
.\generar.ps1       # Excel, scripts, salida real, gráficas/capturas disponibles
.\limpiar.ps1       # desinstalación exclusivamente local del cliente
```

Cada una de las tres operaciones solicita contraseña oculta y la envía por stdin **dentro de SSH**, nunca en argumentos ni historial. La laptop verifica antes de recibir los archivos o invocar Codex. SSH usa clave específica, huella fijada, sin PTY ni reenvíos. El comando forzado acepta sólo `metodos-v1`; el protocolo sólo permite revisar/respuestas/generar. No ofrece una consola PowerShell ni SFTP de libre acceso. El alta HTTPS es independiente y admite sólo claves públicas verificadas. Las transferencias se realizan por el canal cifrado de SSH, en bloques con SHA256, no mediante un servidor adicional.

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

## Resultado de validación de esta actualización

Resultado: **53 pruebas aprobadas y 9 omitidas**. Se ejecutaron pruebas anteriores y nuevas de identidad documentada, ED25519, revocación persistente, rechazos, concurrencia, configuración de arranque y conservación de rutas ajenas. `sshd -t` real acepta la configuración con claves inicialmente vacías; Octave real continúa pasando. Las pruebas del alta usan respuestas WhoIs explícitamente simuladas, no se presentan como conexión real a la tailnet.

El diagnóstico real `bash servidor/preparar_automatico.sh --comprobar` terminó incompleto: este sandbox bloquea sockets de Tailscale y D-Bus, y Codex no puede inicializar su cliente por escritura restringida. La preparación real se detuvo antes de instalar o modificar servicios al no poder consultar systemd de usuario. No se confirmó activación/reinicio/persistencia del servidor. No hay PowerShell/Windows aquí: el bootstrap, la instalación limpia y el alta HTTPS desde Windows siguen pendientes. No se ejecutó limpiar ni se modificaron referencias/resultados. Ejecutar el primer comando fuera de este sandbox y validar el segundo en Windows antes de dejar la laptop sin acceso presencial.

Las pruebas externas incluyen `METODOS_PROBAR_ALTA=1` en un Windows del propietario preparado, con `METODOS_CLAVE_PRUEBA` en el entorno privado. Sólo hacen alta, huella SSH y probe sin tokens. No habilitar estas pruebas automáticamente sobre una PC ajena.
