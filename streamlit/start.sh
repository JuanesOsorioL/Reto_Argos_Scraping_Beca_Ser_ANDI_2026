#!/bin/sh
# Arranca FastAPI control (background) y luego Streamlit (foreground)
set -e

mkdir -p /app/state /app/data

echo "Iniciando FastAPI control en puerto 8010..."
uvicorn api_control:app --host 0.0.0.0 --port 8010 &

echo "Iniciando Streamlit en puerto 8050..."
exec streamlit run app.py \
  --server.port 8050 \
  --server.address 0.0.0.0 \
  --server.headless true \
  --server.fileWatcherType none
