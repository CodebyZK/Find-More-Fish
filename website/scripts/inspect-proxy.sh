#!/bin/sh
# Read-only production diagnostics. Never print environment values or key files.
set -eu

printf '\n--- Deployment account ---\n'
id
printf '\n--- Website authentication boundary ---\n'
for path in /healthz /login /api/csrf-token; do
  curl --max-time 15 -s -o /dev/null -w "$path: %{http_code}\n" "http://127.0.0.1:8081$path" || true
done
if curl --max-time 15 -fsS http://127.0.0.1:8081/login | grep -q 'Continue with GitLab'; then
  echo 'Configured GitLab login is available on the local upstream.'
fi

summarize_nginx() {
  # Only routing/authentication directives, never arbitrary config or secrets.
  sed -n -E '/^# configuration file |^[[:space:]]*(server_name|listen|auth_basic|auth_basic_user_file|include)[[:space:]]/p'
}

printf '\n--- Host Nginx ---\n'
if command -v nginx >/dev/null 2>&1; then
  output=$(mktemp)
  trap 'rm -f "$output"' EXIT
  if nginx -T >"$output" 2>&1; then
    summarize_nginx <"$output"
  elif sudo -n nginx -T >"$output" 2>&1; then
    summarize_nginx <"$output"
  else
    echo 'The deployment account cannot inspect host Nginx configuration.'
    tail -n 3 "$output"
  fi
else
  echo 'No host nginx command on PATH.'
fi

printf '\n--- Containerized proxy services ---\n'
docker ps --format '{{.ID}} {{.Names}} {{.Image}}' | while read -r container_id name image; do
  case "$image" in
    *nginx*|*openresty*|*proxy-manager*|*swag*)
      printf '\nProxy container: %s (%s)\n' "$name" "$image"
      docker inspect --format '{{range .Mounts}}{{.Source}} -> {{.Destination}}{{println}}{{end}}' "$container_id"
      docker exec "$container_id" nginx -T 2>&1 | summarize_nginx
      ;;
  esac
done
