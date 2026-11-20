# Ollama-in-Docker helper for local-sql-analyst-agent (D11/S39), Windows mirror
# of scripts/ollama-docker.sh.
#
# Usage: scripts/ollama-docker.ps1 up|pull <model>|status|down|--check
#
# The container is named ollama-sqlagent, keeps models in the named volume
# ollama-portfolio and publishes 127.0.0.1:11435. "down" never removes the volume.
param(
    [Parameter(Position = 0)]
    [string]$Command = "status",

    [Parameter(Position = 1)]
    [string]$Model = ""
)

$ErrorActionPreference = "Stop"

$Container = if ($env:SQLAGENT_OLLAMA_CONTAINER) { $env:SQLAGENT_OLLAMA_CONTAINER } else { "ollama-sqlagent" }
$Volume = if ($env:SQLAGENT_OLLAMA_VOLUME) { $env:SQLAGENT_OLLAMA_VOLUME } else { "ollama-portfolio" }
$Image = if ($env:SQLAGENT_OLLAMA_IMAGE) { $env:SQLAGENT_OLLAMA_IMAGE } else { "ollama/ollama:0.40.16" }
$HostPort = if ($env:SQLAGENT_OLLAMA_PORT) { $env:SQLAGENT_OLLAMA_PORT } else { "11435" }
$BaseUrl = "http://127.0.0.1:$HostPort"

function Write-Info {
    param([string]$Message)
    Write-Host $Message
}

function Stop-WithError {
    param([string]$Message)
    [Console]::Error.WriteLine("error: $Message")
    exit 1
}

function Show-Usage {
    Write-Info @"
Usage: scripts/ollama-docker.ps1 <command>

Commands:
  up             Create the volume/container if needed, start it and wait for
                 the Ollama API (up to 60 s).
  pull <model>   Pull a model into the container (for example qwen3:8b).
  status         Show container state, Ollama version and loaded models.
  down           Stop and remove the container (the model volume is kept).
  --check        Print Docker/GPU/volume/container status without changing
                 anything. Exits 0 when Docker is usable.
"@
}

function Assert-Docker {
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        Stop-WithError "docker is not installed; install Docker first"
    }
    docker info *> $null
    if ($LASTEXITCODE -ne 0) {
        Stop-WithError "the Docker daemon is not reachable; start Docker and retry"
    }
}

function Test-Volume {
    docker volume inspect $Volume *> $null
    return $LASTEXITCODE -eq 0
}

function Test-Container {
    docker container inspect $Container *> $null
    return $LASTEXITCODE -eq 0
}

function Test-ContainerRunning {
    if (-not (Test-Container)) {
        return $false
    }
    $running = docker container inspect --format "{{.State.Running}}" $Container
    return ($running.Trim() -eq "true")
}

function Test-NvidiaRuntime {
    $runtimes = docker info --format "{{json .Runtimes}}" 2>$null
    return ($runtimes -match '"nvidia"')
}

function Wait-ForApi {
    $deadline = (Get-Date).AddSeconds(60)
    while ((Get-Date) -lt $deadline) {
        try {
            Invoke-RestMethod -Uri "$BaseUrl/api/version" -TimeoutSec 2 *> $null
            return $true
        }
        catch {
            Start-Sleep -Seconds 1
        }
    }
    return $false
}

function Invoke-Up {
    Assert-Docker
    if (-not (Test-Volume)) {
        docker volume create $Volume *> $null
        Write-Info "created volume $Volume"
    }
    if (Test-Container) {
        if (Test-ContainerRunning) {
            Write-Info "container $Container is already running"
        }
        else {
            docker start $Container *> $null
            Write-Info "started existing container $Container"
        }
    }
    else {
        $dockerArgs = @(
            "run", "-d",
            "--name", $Container,
            "--volume", "${Volume}:/root/.ollama",
            "--publish", "127.0.0.1:${HostPort}:11434"
        )
        if (Test-NvidiaRuntime) {
            $dockerArgs += @("--gpus", "all")
            Write-Info "NVIDIA runtime detected; starting with --gpus all"
        }
        else {
            Write-Info "no NVIDIA runtime detected; starting on CPU"
        }
        $dockerArgs += $Image
        docker @dockerArgs *> $null
        if ($LASTEXITCODE -ne 0) {
            Stop-WithError "docker run failed; inspect 'docker logs $Container'"
        }
        Write-Info "created container $Container from $Image"
    }
    if (Wait-ForApi) {
        Write-Info "Ollama is ready at $BaseUrl"
    }
    else {
        Stop-WithError "Ollama did not answer at $BaseUrl within 60 s; run 'status'"
    }
}

function Invoke-Pull {
    if ([string]::IsNullOrWhiteSpace($Model)) {
        Stop-WithError "usage: pull <model> (for example qwen3:8b)"
    }
    Assert-Docker
    if (-not (Test-ContainerRunning)) {
        Stop-WithError "container $Container is not running; run 'up' first"
    }
    docker exec $Container ollama pull $Model
}

function Invoke-Status {
    Assert-Docker
    if (Test-Container) {
        Write-Info "container: $Container"
        docker ps -a --filter "name=^/$Container$" --format "  status={{.Status}} image={{.Image}} ports={{.Ports}}"
        if (Test-ContainerRunning) {
            try {
                $version = Invoke-RestMethod -Uri "$BaseUrl/api/version" -TimeoutSec 3
                Write-Info "version: $($version.version)"
            }
            catch {
                Write-Info "version: unreachable"
            }
            Write-Info "loaded models:"
            docker exec $Container ollama ps
        }
    }
    else {
        Write-Info "container: not created (run 'up')"
    }
    if (Test-Volume) {
        Write-Info "volume: $Volume (kept across down/up)"
    }
    else {
        Write-Info "volume: not created yet"
    }
}

function Invoke-Down {
    Assert-Docker
    if (Test-Container) {
        docker stop $Container *> $null
        docker rm $Container *> $null
        Write-Info "removed container $Container (volume $Volume kept)"
    }
    else {
        Write-Info "container $Container does not exist; nothing to do"
    }
}

function Invoke-Check {
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        Write-Info "docker: not installed"
        exit 1
    }
    Write-Info "docker: $(docker --version)"
    docker info *> $null
    if ($LASTEXITCODE -ne 0) {
        Write-Info "daemon: not reachable"
        exit 1
    }
    Write-Info "daemon: reachable"
    if (Test-NvidiaRuntime) {
        Write-Info "gpu: NVIDIA runtime available (--gpus all will be used)"
    }
    else {
        Write-Info "gpu: no NVIDIA runtime (CPU only)"
    }
    if (Test-Volume) {
        Write-Info "volume: $Volume present"
    }
    else {
        Write-Info "volume: $Volume missing (up creates it)"
    }
    if (Test-Container) {
        if (Test-ContainerRunning) {
            Write-Info "container: $Container running"
        }
        else {
            Write-Info "container: $Container stopped"
        }
    }
    else {
        Write-Info "container: $Container not created"
    }
    exit 0
}

switch ($Command) {
    "up" { Invoke-Up }
    "pull" { Invoke-Pull }
    "status" { Invoke-Status }
    "down" { Invoke-Down }
    "--check" { Invoke-Check }
    "check" { Invoke-Check }
    "--help" { Show-Usage }
    "help" { Show-Usage }
    "" { Show-Usage }
    default {
        Show-Usage
        Stop-WithError "unknown command: $Command"
    }
}
