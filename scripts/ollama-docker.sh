#!/usr/bin/env bash
# Ollama-in-Docker helper for local-sql-analyst-agent (D11/S39).
#
# Usage: scripts/ollama-docker.sh up|pull <model>|status|down|--check
#
# The container is named ollama-sqlagent, keeps models in the named volume
# ollama-portfolio and publishes 127.0.0.1:11435.  Nothing is ever deleted from
# the volume; "down" only stops and removes the container.
set -euo pipefail

CONTAINER="${SQLAGENT_OLLAMA_CONTAINER:-ollama-sqlagent}"
VOLUME="${SQLAGENT_OLLAMA_VOLUME:-ollama-portfolio}"
IMAGE="${SQLAGENT_OLLAMA_IMAGE:-ollama/ollama:0.40.16}"
HOST_PORT="${SQLAGENT_OLLAMA_PORT:-11435}"
BASE_URL="http://127.0.0.1:${HOST_PORT}"

info() {
  printf '%s\n' "$*"
}

die() {
  printf 'error: %s\n' "$*" >&2
  exit 1
}

usage() {
  cat <<'EOF'
Usage: scripts/ollama-docker.sh <command>

Commands:
  up             Create the volume/container if needed, start it and wait for
                 the Ollama API (up to 60 s).
  pull <model>   Pull a model into the container (for example qwen3:8b).
  status         Show container state, Ollama version and loaded models.
  down           Stop and remove the container (the model volume is kept).
  --check        Print Docker/GPU/volume/container status without changing
                 anything. Exits 0 when Docker is usable.
EOF
}

require_docker() {
  command -v docker >/dev/null 2>&1 || die "docker is not installed; install Docker first"
  if ! docker info >/dev/null 2>&1; then
    die "the Docker daemon is not reachable; start Docker and retry"
  fi
}

require_curl() {
  command -v curl >/dev/null 2>&1 || die "curl is required to probe the Ollama API"
}

volume_exists() {
  docker volume inspect "$VOLUME" >/dev/null 2>&1
}

container_exists() {
  docker container inspect "$CONTAINER" >/dev/null 2>&1
}

container_running() {
  if ! container_exists; then
    return 1
  fi
  [ "$(docker container inspect --format '{{.State.Running}}' "$CONTAINER")" = "true" ]
}

has_nvidia_runtime() {
  docker info --format '{{json .Runtimes}}' 2>/dev/null | grep -q '"nvidia"'
}

wait_for_api() {
  local deadline=$((SECONDS + 60))
  while [ "$SECONDS" -lt "$deadline" ]; do
    if curl -fsS "${BASE_URL}/api/version" >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
  done
  return 1
}

command_up() {
  require_docker
  require_curl
  if ! volume_exists; then
    docker volume create "$VOLUME" >/dev/null
    info "created volume $VOLUME"
  fi
  if container_exists; then
    if container_running; then
      info "container $CONTAINER is already running"
    else
      docker start "$CONTAINER" >/dev/null
      info "started existing container $CONTAINER"
    fi
  else
    local args=(
      run -d
      --name "$CONTAINER"
      --volume "${VOLUME}:/root/.ollama"
      --publish "127.0.0.1:${HOST_PORT}:11434"
    )
    if has_nvidia_runtime; then
      args+=(--gpus all)
      info "NVIDIA runtime detected; starting with --gpus all"
    else
      info "no NVIDIA runtime detected; starting on CPU"
    fi
    docker "${args[@]}" "$IMAGE" >/dev/null
    info "created container $CONTAINER from $IMAGE"
  fi
  if wait_for_api; then
    info "Ollama is ready at $BASE_URL"
  else
    die "Ollama did not answer at $BASE_URL within 60 s; run '$0 status'"
  fi
}

command_pull() {
  if [ "$#" -lt 1 ] || [ -z "$1" ]; then
    die "usage: $0 pull <model> (for example qwen3:8b)"
  fi
  require_docker
  container_running || die "container $CONTAINER is not running; run '$0 up' first"
  docker exec "$CONTAINER" ollama pull "$1"
}

command_status() {
  require_docker
  if container_exists; then
    info "container: $CONTAINER"
    docker ps -a --filter "name=^/${CONTAINER}$" --format \
      '  status={{.Status}} image={{.Image}} ports={{.Ports}}'
    if container_running; then
      if command -v curl >/dev/null 2>&1; then
        info "version: $(curl -fsS "${BASE_URL}/api/version" || printf 'unreachable')"
      fi
      info "loaded models:"
      docker exec "$CONTAINER" ollama ps || true
    fi
  else
    info "container: not created (run '$0 up')"
  fi
  if volume_exists; then
    info "volume: $VOLUME (kept across down/up)"
  else
    info "volume: not created yet"
  fi
}

command_down() {
  require_docker
  if container_exists; then
    docker stop "$CONTAINER" >/dev/null 2>&1 || true
    docker rm "$CONTAINER" >/dev/null
    info "removed container $CONTAINER (volume $VOLUME kept)"
  else
    info "container $CONTAINER does not exist; nothing to do"
  fi
}

command_check() {
  if ! command -v docker >/dev/null 2>&1; then
    info "docker: not installed"
    exit 1
  fi
  info "docker: $(docker --version)"
  if ! docker info >/dev/null 2>&1; then
    info "daemon: not reachable"
    exit 1
  fi
  info "daemon: reachable"
  if has_nvidia_runtime; then
    info "gpu: NVIDIA runtime available (--gpus all will be used)"
  else
    info "gpu: no NVIDIA runtime (CPU only)"
  fi
  if volume_exists; then
    info "volume: $VOLUME present"
  else
    info "volume: $VOLUME missing (up creates it)"
  fi
  if container_exists; then
    if container_running; then
      info "container: $CONTAINER running"
    else
      info "container: $CONTAINER stopped"
    fi
  else
    info "container: $CONTAINER not created"
  fi
  if command -v curl >/dev/null 2>&1; then
    info "curl: available"
  else
    info "curl: missing (up cannot wait for the API)"
  fi
}

main() {
  case "${1:-}" in
    up) command_up ;;
    pull) shift; command_pull "$@" ;;
    status) command_status ;;
    down) command_down ;;
    --check | check) command_check ;;
    -h | --help | help | "") usage ;;
    *) usage >&2; die "unknown command: $1" ;;
  esac
}

main "$@"
