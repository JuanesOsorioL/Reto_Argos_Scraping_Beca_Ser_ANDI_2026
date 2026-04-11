/**
 * api_runner.js — Endpoint HTTP para que n8n dispare el scraper RUES.
 * Puerto: 8006
 *
 * Endpoints:
 *   POST /scrape/rues          → corrida completa (todas las keywords)
 *   POST /scrape/rues/prueba   → prueba rápida (1 keyword, 5 registros)
 *   GET  /status               → estado actual
 *   GET  /resultado            → resultado última corrida
 */

// Importa Express para exponer una API HTTP simple que dispare el scraper.
const express = require('express');
// Importa axios para notificar a n8n cuando termine el proceso.
const axios = require('axios');
// Importa uuid v4 para generar identificadores únicos de cada corrida.
const { v4: uuidv4 } = require('uuid');
// Importa el logger central para dejar trazabilidad operativa del runner HTTP.
const { logger } = require('./logger');
// Importa el orquestador principal que ejecuta la corrida completa del scraper.
const { do_scrape } = require('./main');

// Crea la instancia principal de la aplicación Express.
const app = express();
// Habilita el parseo automático de cuerpos JSON entrantes.
app.use(express.json());

// URL fija del webhook de n8n.
//todoen docker
const N8N_WEBHOOK_URL = process.env.N8N_WEBHOOK_URL;

// Define un estado global en memoria para exponer el progreso y el último resultado de la API.
const estado = {
  scraping_en_curso: false,
  run_id: null,
  inicio: null,
  fin: null,
  duracion: null,
  ultimo_status: 'sin_correr',
  ultimo_error: null,
  metricas: null,
};

// Calcula una duración legible a partir de dos fechas.
function calcularDuracion(inicioIso, finIso) {
  if (!inicioIso || !finIso) return null;
  const inicio = new Date(inicioIso);
  const fin = new Date(finIso);
  const duracionS = Math.max(0, Math.round((fin - inicio) / 1000));
  return `${Math.floor(duracionS / 60)}m ${duracionS % 60}s`;
}

// Envía el callback a n8n cuando termina el proceso.
async function enviarCallback(payload, headers = {}) {
  await axios.post(N8N_WEBHOOK_URL, payload, {
    timeout: 15000,
    headers: {
      'Content-Type': 'application/json',
      ...headers
    }
  });
}

// Intenta notificar a n8n, pero sin romper el flujo principal si falla.
async function notificarFinRun(payload, headers = {}) {
  try {
    await enviarCallback(payload, headers);
    logger.ok(`[CALLBACK] Notificación enviada a n8n. evento=${payload.evento} run_id=${payload.run_id}`);
  } catch (e) {
    logger.error(`[CALLBACK] Falló envío a n8n: ${e.message}`);
  }
}

// Dispara una corrida en segundo plano sin bloquear la respuesta HTTP inicial.
function ejecutarBackground(opciones, extra = {}) {
  const run_id = uuidv4();

  estado.scraping_en_curso = true;
  estado.run_id = run_id;
  estado.inicio = new Date().toISOString();
  estado.fin = null;
  estado.duracion = null;
  estado.ultimo_status = 'corriendo';
  estado.ultimo_error = null;
  estado.metricas = null;

  do_scrape(opciones)
    .then(async (metricas) => {
      const fin = new Date().toISOString();

      estado.scraping_en_curso = false;
      estado.fin = fin;
      estado.duracion = metricas?.duracion ?? calcularDuracion(estado.inicio, fin);
      estado.ultimo_status = 'ok';
      estado.ultimo_error = null;
      estado.metricas = metricas;

      logger.ok(`[API] RUES completado. run_id: ${run_id}`);

      await notificarFinRun({
        evento: 'rues.finalizado',
        status: 'ok',
        run_id,
        inicio: estado.inicio,
        fin: estado.fin,
        duracion: estado.duracion,
        metricas,
        origen: 'api_runner',
        tipo_ejecucion: extra.tipo_ejecucion ?? 'produccion'
      });
    })
    .catch(async (e) => {
      const fin = new Date().toISOString();

      estado.scraping_en_curso = false;
      estado.fin = fin;
      estado.duracion = calcularDuracion(estado.inicio, fin);
      estado.ultimo_status = 'error';
      estado.ultimo_error = e.message;
      estado.metricas = null;

      logger.error(`[API] RUES falló: ${e.message}`);

      await notificarFinRun({
        evento: 'rues.finalizado',
        status: 'error',
        run_id,
        inicio: estado.inicio,
        fin: estado.fin,
        duracion: estado.duracion,
        error: e.message,
        origen: 'api_runner',
        tipo_ejecucion: extra.tipo_ejecucion ?? 'produccion'
      });
    });

  return run_id;
}

app.get('/health', (req, res) => res.json({ status: 'ok',code:"200" }));



// Expone un endpoint GET para consultar el estado actual del proceso.
app.get('/status', (req, res) => {
  res.json({
    status: estado.ultimo_status,
    en_curso: estado.scraping_en_curso,
    run_id: estado.run_id,
    inicio: estado.inicio,
    fin: estado.fin,
    duracion: estado.duracion,
    error: estado.ultimo_error,
    metricas: estado.metricas,
  });
});

// Expone un endpoint POST para lanzar la corrida completa de producción.
app.post('/scrape/rues', (req, res) => {
  if (estado.scraping_en_curso) {
    return res.status(409).json({ status: 'ocupado', run_id: estado.run_id });
  }

  const run_id = ejecutarBackground(
    {
      details: true,
      extended: true,
      concurrency: 1,
      delayMs: 1200,
    },
    {
      tipo_ejecucion: 'produccion'
    }
  );

  res.json({
    status: 'iniciado',
    run_id,
    inicio: estado.inicio,
    webhook_n8n: N8N_WEBHOOK_URL,
    mensaje: 'RUES scraper disparado. Consulta /status para ver el progreso.',
  });
});

// Expone un endpoint POST para lanzar una corrida reducida de prueba.
app.post('/scrape/rues/prueba', (req, res) => {
  if (estado.scraping_en_curso) {
    return res.status(409).json({ status: 'ocupado', run_id: estado.run_id });
  }

  const run_id = ejecutarBackground(
    {
      details: true,
      extended: true,
      keywords: ['ferreterias'],
      limit: 5,
      concurrency: 1,
      delayMs: 1200,
    },
    {
      tipo_ejecucion: 'prueba'
    }
  );

  res.json({
    status: 'iniciado',
    run_id,
    inicio: estado.inicio,
    webhook_n8n: N8N_WEBHOOK_URL,
    mensaje: 'Prueba RUES iniciada (1 keyword, 5 registros).',
  });
});

// Expone un endpoint GET que entrega el estado compacto orientado a resultado reciente.
app.get('/resultado', (req, res) => {
  res.json({
    status: estado.ultimo_status,
    run_id: estado.run_id,
    inicio: estado.inicio,
    fin: estado.fin,
    duracion: estado.duracion,
    error: estado.ultimo_error,
    en_curso: estado.scraping_en_curso,
    metricas: estado.metricas,
  });
});


// Expone un endpoint para probar manualmente el callback hacia n8n sin ejecutar el scraper.
app.post('/test/callback', async (req, res) => {
  try {
    // Permite sobreescribir algunos campos desde el body para pruebas manuales.
    const body = req.body || {};

    // Arma un payload de prueba parecido al que se enviará al finalizar un run real.
    const payload = {
      evento: 'rues.finalizado',
      status: body.status || 'ok',
      run_id: body.run_id || 'test-run-001',
      inicio: body.inicio || new Date(Date.now() - 65000).toISOString(),
      fin: body.fin || new Date().toISOString(),
      duracion: body.duracion || '1m 5s',
      metricas: body.metricas || {
        run_id: body.run_id || 'test-run-001',
        inicio: body.inicio || new Date(Date.now() - 65000).toISOString(),
        fin: body.fin || new Date().toISOString(),
        duracion: body.duracion || '1m 5s',
        keywords_total: 1,
        keywords_procesadas: 1,
        busqueda_total: 5,
        detalle_ok: 4,
        detalle_error: 1,
        detalle_saltado: 0,
        facultades_ok: 3,
        facultades_error: 0,
        propietarios_ok: 3,
        propietarios_error: 0,
        aprobados_argos: 2,
        errores_totales: 1
      },
      origen: 'api_runner',
      tipo_ejecucion: body.tipo_ejecucion || 'prueba_callback'
    };

    // Si quieres probar error, limpia metricas y agrega error.
    if (payload.status === 'error') {
      delete payload.metricas;
      payload.error = body.error || 'Error de prueba enviado manualmente';
    }

    // Envía el callback al webhook de n8n.
    await enviarCallback(payload);

    // Responde con lo que fue enviado para validar fácilmente.
    return res.json({
      status: 'ok',
      mensaje: 'Callback de prueba enviado a n8n correctamente',
      webhook_n8n: N8N_WEBHOOK_URL,
      payload_enviado: payload
    });
  } catch (e) {
    logger.error(`[TEST_CALLBACK] Falló envío de prueba a n8n: ${e.message}`);
    return res.status(500).json({
      status: 'error',
      mensaje: 'No se pudo enviar el callback de prueba a n8n',
      error: e.message
    });
  }
});





app.get("/endpoints", (req, res) => {
  const endpoints = [];

  app._router.stack.forEach((middleware) => {
    if (middleware.route) {
      endpoints.push({
        path: middleware.route.path,
        methods: Object.keys(middleware.route.methods).map((m) => m.toUpperCase()),
      });
    } else if (middleware.name === "router" && middleware.handle.stack) {
      middleware.handle.stack.forEach((handler) => {
        if (handler.route) {
          endpoints.push({
            path: handler.route.path,
            methods: Object.keys(handler.route.methods).map((m) => m.toUpperCase()),
          });
        }
      });
    }
  });

  res.json(endpoints);
});









// Toma el puerto desde variable de entorno o usa 8006 como valor por defecto.
const PORT = process.env.PORT || 8006;
// Inicia el servidor HTTP escuchando en el puerto configurado.
app.listen(PORT, () => {
  logger.ok(`[API] RUES API en http://localhost:${PORT}`);
  logger.info(`       n8n: http://host.docker.internal:${PORT}`);
  logger.info(`       webhook n8n destino: ${N8N_WEBHOOK_URL}`);
  logger.info(`       POST /scrape/rues          → producción completa`);
  logger.info(`       POST /scrape/rues/prueba   → test rápido`);
  logger.info(`       GET  /status               → estado actual`);
  logger.info(`       GET  /resultado            → resultado última corrida`);
});

// Exporta la app para posibles tests o integración externa.
module.exports = app;