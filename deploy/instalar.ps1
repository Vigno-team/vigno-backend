# Instala y levanta el sistema completo con un solo comando (E1C-141). Windows.
#
#   powershell -ExecutionPolicy Bypass -File deploy\instalar.ps1
#
# Crea deploy\.env con claves aleatorias, crea el certificado de prueba para localhost y levanta
# base, backend, tareas, respaldos y frontend. Se puede volver a correr: no cambia las claves ni
# el certificado que ya existen. El administrador por defecto lo crea el backend (E1C-138).
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
$envArchivo = "deploy/.env"

function Falla($mensaje) { Write-Host "ERROR: $mensaje" -ForegroundColor Red; exit 1 }
function Paso($mensaje) { Write-Host ""; Write-Host "==> $mensaje" -ForegroundColor Cyan }

function Leer($clave) {
    foreach ($linea in [IO.File]::ReadAllLines((Resolve-Path $envArchivo).Path)) {
        if ($linea.StartsWith("$clave=")) { return $linea.Substring($clave.Length + 1).Trim() }
    }
    return ""
}
function Poner($clave, $valor) {
    $lineas = [Collections.Generic.List[string]]([IO.File]::ReadAllLines((Resolve-Path $envArchivo).Path))
    $hecho = $false
    for ($i = 0; $i -lt $lineas.Count; $i++) {
        if ($lineas[$i].StartsWith("$clave=")) { $lineas[$i] = "$clave=$valor"; $hecho = $true }
    }
    if (-not $hecho) { $lineas.Add("$clave=$valor") }
    # LF y sin BOM, igual que en Linux y macOS.
    [IO.File]::WriteAllText((Resolve-Path $envArchivo).Path, (($lineas -join "`n") + "`n"), (New-Object Text.UTF8Encoding($false)))
}
# Solo letras y numeros: no hay que escaparlos en .env ni en la URL de la base.
function Aleatorio {
    $letras = [char[]]"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
    $bytes = New-Object byte[] 64
    $rng = New-Object Security.Cryptography.RNGCryptoServiceProvider
    $rng.GetBytes($bytes)
    $rng.Dispose()
    return -join ($bytes | ForEach-Object { $letras[$_ % $letras.Length] })
}

Paso "Revisando Docker"
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { Falla "No se encontro Docker. Instala Docker Desktop." }
# En PowerShell 5.1, redirigir la salida de error de un programa con "Stop" convierte cualquier
# aviso de Docker en un error que corta el script: aqui se revisa solo el codigo de salida.
$ErrorActionPreference = "Continue"
docker info *> $null
$dockerCorre = $LASTEXITCODE -eq 0
docker compose version *> $null
$hayCompose = $LASTEXITCODE -eq 0
$ErrorActionPreference = "Stop"
if (-not $dockerCorre) { Falla "Docker no esta corriendo. Abre Docker Desktop y vuelve a intentar." }
if (-not $hayCompose) { Falla "Falta Docker Compose v2 (el comando 'docker compose')." }

Paso "Configuracion ($envArchivo)"
$nuevo = $false
if (-not (Test-Path $envArchivo)) {
    Copy-Item deploy/.env.example $envArchivo
    $nuevo = $true
    Write-Host "Creado desde deploy/.env.example."
} else {
    Write-Host "Ya existe: se conserva y solo se completan las claves vacias."
}
foreach ($clave in @("SECRET_KEY", "POSTGRES_PASSWORD")) {
    if (-not (Leer $clave)) {
        Poner $clave (Aleatorio)
        Write-Host "$clave generada."
    }
}
if ($nuevo) {
    # Instalacion local con certificado de prueba: se entra con admin@sistema.local / admin y
    # hay que cambiar la clave al entrar (E1C-138). En un servidor publico, apagar (README).
    Poner "ADMIN_POR_DEFECTO" "True"
}

Paso "Frontend"
$frontend = Leer "FRONTEND_DIR"
if (-not $frontend) { $frontend = "../../frontend" }
if ([IO.Path]::IsPathRooted($frontend)) { $rutaFrontend = $frontend } else { $rutaFrontend = Join-Path "deploy" $frontend }
if (-not (Test-Path (Join-Path $rutaFrontend "package.json"))) {
    $destino = [IO.Path]::GetFullPath((Join-Path (Get-Location) $rutaFrontend))
    Falla ("No esta el frontend en $destino (FRONTEND_DIR en $envArchivo). Clonalo al lado del backend:`n" +
        "    git clone --branch develop https://github.com/Vigno-team/vigno-fronted.git `"$destino`"`n" +
        "o cambia FRONTEND_DIR en $envArchivo, y vuelve a correr este instalador.")
}
Write-Host "Encontrado en $rutaFrontend."

Paso "Certificado de prueba para localhost"
if ((Test-Path deploy/certs/fullchain.pem) -and (Test-Path deploy/certs/privkey.pem)) {
    Write-Host "Ya existe: se conserva."
} else {
    New-Item -ItemType Directory -Force deploy/certs | Out-Null
    $certs = (Resolve-Path deploy/certs).Path
    docker run --rm --mount "type=bind,source=$certs,target=/certs" --entrypoint sh alpine/openssl:3.5.9 -c "openssl req -x509 -nodes -days 30 -newkey rsa:3072 -keyout /certs/privkey.pem -out /certs/fullchain.pem -subj /CN=localhost -addext subjectAltName=DNS:localhost,IP:127.0.0.1 && chown 101:101 /certs/privkey.pem && chmod 640 /certs/privkey.pem"
    if ($LASTEXITCODE -ne 0) { Falla "No se pudo crear el certificado." }
    Write-Host "Creado (dura 30 dias; el navegador avisara que no es de una autoridad publica)."
}

Paso "Construyendo y levantando (la primera vez tarda varios minutos)"
docker compose --env-file $envArchivo -f deploy/docker-compose.yml up --build -d --wait --wait-timeout 900
if ($LASTEXITCODE -ne 0) { Falla "No se pudo levantar. Revisa: docker compose --env-file $envArchivo -f deploy/docker-compose.yml logs" }

$puerto = Leer "HTTPS_PORT"
$direccion = "https://localhost"
if ($puerto -and $puerto -ne "443") { $direccion = "https://localhost:$puerto" }
Write-Host ""
Write-Host "Listo. Abre $direccion" -ForegroundColor Green
if ((Leer "ADMIN_POR_DEFECTO") -eq "True") {
    Write-Host "Entra con admin@sistema.local / admin. Te pedira cambiar la clave en el primer ingreso."
} else {
    Write-Host "Entra con la cuenta de DJANGO_SUPERUSER_EMAIL de $envArchivo."
}
Write-Host "Para apagar: docker compose --env-file $envArchivo -f deploy/docker-compose.yml down"
