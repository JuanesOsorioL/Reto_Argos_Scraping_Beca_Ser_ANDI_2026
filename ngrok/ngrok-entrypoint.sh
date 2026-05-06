#!/bin/sh
set -e

OUT_DIR="/shared"
N8N_ENV_FILE="$OUT_DIR/n8n-ngrok.env"

mkdir -p "$OUT_DIR"

# Lanzar túnel n8n con dominio estático
echo "[NGROK] Lanzando túnel n8n en ${NGROK_DOMAIN} -> argos_n8n:5678 ..."
ngrok http \
  --config /etc/ngrok.yml \
  --domain "${NGROK_DOMAIN}" \
  argos_n8n:5678 \
  >/tmp/ngrok.log 2>&1 &

# Esperar a que la API esté disponible
echo "[NGROK] Esperando API local..."
for i in $(seq 1 60); do
  if curl -fsS http://127.0.0.1:4040/api/tunnels >/dev/null 2>&1; then
    echo "[NGROK] API disponible en intento $i"
    break
  fi
  echo "[NGROK] intento $i/60 - API aún no disponible"
  if [ "$i" = "5" ]; then
    echo "[NGROK] === LOG NGROK (intento 5) ==="
    cat /tmp/ngrok.log 2>/dev/null || echo "(log vacío)"
    echo "[NGROK] ================================"
  fi
  sleep 2
done

# Obtener URL pública del túnel n8n
N8N_URL=$(curl -fsS http://127.0.0.1:4040/api/tunnels \
  | grep -o '"public_url":"https:[^"]*"' | head -n 1 | cut -d'"' -f4)

if [ -z "$N8N_URL" ]; then
  echo "[NGROK] ERROR: no pude obtener la URL de n8n"
  cat /tmp/ngrok.log || true
  exit 1
fi

# Generar env de n8n
cat > "$N8N_ENV_FILE" <<EOF
WEBHOOK_URL=$N8N_URL/
N8N_EDITOR_BASE_URL=$N8N_URL
N8N_PROXY_HOPS=1
EOF

echo "[NGROK] n8n listo en: $N8N_URL"

wait
