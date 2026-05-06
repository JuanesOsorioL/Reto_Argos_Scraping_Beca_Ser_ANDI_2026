#!/bin/sh
mkdir -p /shared

echo "[CF] Iniciando tunnel hacia argos-dashboard:8050 ..."
cloudflared tunnel --url http://argos-dashboard:8050 >/tmp/cf.log 2>&1 &

# Esperar hasta que aparezca la URL en el log
for i in $(seq 1 30); do
  URL=$(grep -o 'https://[^[:space:]|]*trycloudflare\.com' /tmp/cf.log 2>/dev/null | head -1)
  if [ -n "$URL" ]; then
    echo "$URL" > /shared/dashboard-url.txt
    echo "[CF] URL guardada: $URL"
    break
  fi
  echo "[CF] esperando URL... intento $i/30"
  sleep 2
done

if [ -z "$URL" ]; then
  echo "[CF] ERROR: no se pudo obtener URL"
  cat /tmp/cf.log
fi

# Mantener el contenedor vivo mostrando logs
tail -f /tmp/cf.log
