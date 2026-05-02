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

// Índice invertido: nombre normalizado → código.
const NOMBRE_A_CODIGO = Object.fromEntries(
  Object.entries(CAMARAS).map(([code, name]) => [name, code])
);

// Elimina tildes, convierte a mayúsculas y elimina espacios extremos.
function normalizarNombre(str) {
  if (!str) return '';
  return String(str)
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .toUpperCase()
    .trim();
}

// Dado un array de nombres de municipio, devuelve los que existen en el mapeo
// y los que no, conservando el valor original recibido.
function resolverMunicipios(municipios) {
  const encontrados    = [];
  const no_encontrados = [];

  for (const mun of municipios) {
    const normalizado = normalizarNombre(mun);
    const cod_camara  = NOMBRE_A_CODIGO[normalizado];
    if (cod_camara) {
      encontrados.push({ municipio_original: mun, municipio_normalizado: normalizado, cod_camara });
    } else {
      no_encontrados.push(mun);
    }
  }

  return { encontrados, no_encontrados };
}

// Lista de todos los códigos disponibles en el mapeo.
const TODOS_LOS_CODIGOS = Object.keys(CAMARAS);

module.exports = { CAMARAS, normalizarNombre, resolverMunicipios, TODOS_LOS_CODIGOS };
