// Mapeo oficial de códigos de Cámara de Comercio de Colombia.
const CAMARAS = {
  '01': 'ARMENIA',
  '02': 'BARRANCABERMEJA',
  '03': 'BARRANQUILLA',
  '04': 'BOGOTA',
  '05': 'BUCARAMANGA',
  '07': 'BUGA',
  '08': 'CALI',
  '09': 'CARTAGENA',
  '10': 'CARTAGO',
  '11': 'CUCUTA',
  '12': 'CHINCHINA',
  '13': 'DUITAMA',
  '14': 'GIRARDOT',
  '15': 'HONDA',
  '16': 'IBAGUE',
  '17': 'IPIALES',
  '18': 'LA DORADA',
  '20': 'MANIZALES',
  '21': 'MEDELLIN',
  '22': 'MONTERIA',
  '23': 'HUILA',
  '24': 'PALMIRA',
  '25': 'PAMPLONA',
  '26': 'PASTO',
  '27': 'PEREIRA',
  '28': 'CAUCA',
  '29': 'CHOCO',
  '30': 'LA GUAJIRA',
  '31': 'SAN ANDRES',
  '32': 'SANTA MARTA',
  '33': 'SANTA ROSA DE CABAL',
  '34': 'SINCELEJO',
  '35': 'SOGAMOSO',
  '36': 'TULUA',
  '37': 'TUMACO',
  '38': 'TUNJA',
  '39': 'VALLEDUPAR',
  '40': 'VILLAVICENCIO',
  '41': 'FLORENCIA',
  '42': 'AMAZONAS',
  '44': 'URABA',
  '45': 'TOLIMA',
  '46': 'PUTUMAYO',
  '47': 'FACATATIVA',
  '48': 'ARAUCA',
  '49': 'OCANA',
  '50': 'CASANARE',
  '51': 'ORIENTE ANTIOQUENO',
  '52': 'MAGDALENA MEDIO',
  '53': 'AGUACHICA',
  '54': 'DOSQUEBRADAS',
  '55': 'ABURRA SUR',
  '56': 'PIEDEMONTE ARAUCANO',
  '57': 'SAN JOSE',
  '58': 'SOACHA',
};

// Índice invertido: nombre de cámara normalizado → código.
const NOMBRE_A_CODIGO = Object.fromEntries(
  Object.entries(CAMARAS).map(([code, name]) => [name, code])
);

// Mapa extendido: nombre de municipio normalizado → código de cámara.
// Cubre municipios cuyo nombre no coincide con el nombre oficial de la cámara.
const MUNICIPIOS_EXTENDIDOS = {
  // Aburrá Sur (55)
  'SABANETA':             '55',
  'ITAGUI':               '55',
  'LA ESTRELLA':          '55',
  'ENVIGADO':             '55',
  'CALDAS':               '55',
  // Medellín - área metropolitana norte y occidente (21)
  'BELLO':                '21',
  'COPACABANA':           '21',
  'GIRARDOTA':            '21',
  'BARBOSA':              '21',
  'YARUMAL':              '21',
  'DON MATIAS':           '21',
  'ENTRERRIOS':           '21',
  'SANTA ROSA DE OSOS':   '21',
  'SANTAFE DE ANTIOQUIA': '21',
  'URRAO':                '21',
  'FRONTINO':             '21',
  'LIBORINA':             '21',
  'URAMITA':              '21',
  'SABANALARGA':          '21',
  // Urabá (44)
  'TURBO':                '44',
  'CHIGORODO':            '44',
  'APARTADO':             '44',
  'CAREPA':               '44',
  'MUTATA':               '44',
  // Oriente Antioqueño (51)
  'GUARNE':               '51',
  'MARINILLA':            '51',
  'PENOL':                '51',
  'LA CEJA':              '51',
  'SAN RAFAEL':           '51',
  'GUATAPE':              '51',
  'SONSON':               '51',
  'RIONEGRO':             '51',
  'EL RETIRO':            '51',
  'LA UNION':             '51',
  'ABEJORRAL':            '51',
  'CONCEPCION':           '51',
  // Magdalena Medio (52)
  'PUERTO BERRIO':        '52',
  'SEGOVIA':              '52',
  'REMEDIOS':             '52',
  'ZARAGOZA':             '52',
  'YONDO':                '52',
};

// Elimina tildes, convierte a mayúsculas y elimina espacios extremos.
function normalizarNombre(str) {
  if (!str) return '';
  return String(str)
    .normalize('NFD')
    .replace(/[̀-ͯ]/g, '')
    .toUpperCase()
    .trim();
}

// Dado un array de nombres de municipio/cámara, agrupa por código de cámara único.
// Evita búsquedas duplicadas cuando varios municipios pertenecen a la misma cámara.
// Retorna:
//   plan            → [{ cod_camara, nombre_camara, municipios_cubiertos[] }]
//   no_encontrados  → nombres que no matchearon ninguna cámara ni municipio
function agruparPorCamara(municipios) {
  // Acumula: cod_camara → { nombre_camara, municipios_cubiertos[] }
  const porCodigo      = {};
  const no_encontrados = [];

  for (const mun of municipios) {
    const normalizado = normalizarNombre(mun);

    // Busca primero en nombres de cámara directos, luego en municipios extendidos.
    const cod_camara = NOMBRE_A_CODIGO[normalizado] ?? MUNICIPIOS_EXTENDIDOS[normalizado] ?? null;

    if (cod_camara) {
      if (!porCodigo[cod_camara]) {
        porCodigo[cod_camara] = {
          cod_camara,
          nombre_camara:        CAMARAS[cod_camara],
          municipios_cubiertos: [],
        };
      }
      porCodigo[cod_camara].municipios_cubiertos.push(mun);
    } else {
      no_encontrados.push(mun);
    }
  }

  // El plan es la lista deduplicada de cámaras a consultar.
  const plan = Object.values(porCodigo);

  return { plan, no_encontrados };
}

// Mantiene resolverMunicipios para compatibilidad, internamente usa agruparPorCamara.
function resolverMunicipios(municipios) {
  const { plan, no_encontrados } = agruparPorCamara(municipios);
  const encontrados = plan.flatMap(p =>
    p.municipios_cubiertos.map(m => ({
      municipio_original:    m,
      municipio_normalizado: normalizarNombre(m),
      cod_camara:            p.cod_camara,
    }))
  );
  return { encontrados, no_encontrados };
}

// Lista de todos los códigos disponibles en el mapeo principal.
const TODOS_LOS_CODIGOS = Object.keys(CAMARAS);

module.exports = {
  CAMARAS,
  MUNICIPIOS_EXTENDIDOS,
  normalizarNombre,
  resolverMunicipios,
  agruparPorCamara,
  TODOS_LOS_CODIGOS,
};
