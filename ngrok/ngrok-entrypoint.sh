#!/bin/sh
set -e

OUT_DIR="/shared"
OUT_FILE="$OUT_DIR/n8n-ngrok.env"

mkdir -p "$OUT_DIR"

echo "[NGROK] Lanzando túnel a ${TARGET_HOST}:${TARGET_PORT} ..."
ngrok http "${TARGET_HOST}:${TARGET_PORT}" >/tmp/ngrok.log 2>&1 &

echo "[NGROK] Esperando API local..."
for i in $(seq 1 60); do
  if curl -fsS http://127.0.0.1:4040/api/tunnels >/dev/null 2>&1; then
    break
  fi
  echo "[NGROK] intento $i/60 - API aún no disponible"
  sleep 2
done

PUBLIC_URL=$(curl -fsS http://127.0.0.1:4040/api/tunnels | \
  grep -o '"public_url":"https:[^"]*"' | head -n 1 | cut -d'"' -f4)

if [ -z "$PUBLIC_URL" ]; then
  echo "[NGROK] ERROR: no pude obtener la URL pública"
  echo "----- LOG NGROK -----"
  cat /tmp/ngrok.log || true
  exit 1
fi

HOST_ONLY=$(echo "$PUBLIC_URL" | sed 's#https://##')

cat > "$OUT_FILE" <<EOF
WEBHOOK_URL=$PUBLIC_URL/
N8N_EDITOR_BASE_URL=$PUBLIC_URL
N8N_PROXY_HOPS=1
EOF

echo "[NGROK] Archivo generado:"
cat "$OUT_FILE"

wait