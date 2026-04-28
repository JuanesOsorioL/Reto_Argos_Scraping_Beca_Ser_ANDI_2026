"""
tests/test_normalizacion.py - Tests unitarios para funciones de normalización
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from services.normalizacion import (
    normalizar_nombre,
    normalizar_telefono,
    normalizar_correo,
    normalizar_direccion,
    clasificar_telefono,
)


def test_normalizar_nombre():
    casos = [
        ("FERRETERÍA EL ÉXITO S.A.S.", "ferreteria el exito"),
        ("El Diamante Ltda.", "el diamante"),
        ("ferretería constructor", "ferreteria constructor"),
        ("HIERROS Y FERRETERÍAS SA", "hierros y ferreterias"),
        (None, None),
        ("", None),
        ("   ", None),
    ]
    for entrada, esperado in casos:
        resultado = normalizar_nombre(entrada)
        assert resultado == esperado, f"Para '{entrada}' esperaba '{esperado}', obtuve '{resultado}'"
    print("✅ test_normalizar_nombre: PASS")


def test_normalizar_telefono():
    casos = [
        ("+57 300 1234567", "3001234567"),
        ("604-444-5566", "6044445566"),
        ("57 3001234567", "3001234567"),
        ("(300) 123-4567", "3001234567"),
        ("123", None),      # muy corto
        (None, None),
        ("", None),
    ]
    for entrada, esperado in casos:
        resultado = normalizar_telefono(entrada)
        assert resultado == esperado, f"Para '{entrada}' esperaba '{esperado}', obtuve '{resultado}'"
    print("✅ test_normalizar_telefono: PASS")


def test_normalizar_correo():
    casos = [
        ("INFO@EMPRESA.COM", "info@empresa.com"),
        ("  ventas@ferreteria.co  ", "ventas@ferreteria.co"),
        ("no-es-email", None),
        ("faltaarroba.com", None),
        (None, None),
        ("", None),
    ]
    for entrada, esperado in casos:
        resultado = normalizar_correo(entrada)
        assert resultado == esperado, f"Para '{entrada}' esperaba '{esperado}', obtuve '{resultado}'"
    print("✅ test_normalizar_correo: PASS")


def test_normalizar_direccion():
    casos = [
        ("Cra 50 No 10-20", "carrera 50 # 10 20"),
        ("Cl 45 # 12-34", "calle 45 # 12 34"),
        ("Av El Poblado 100", "avenida el poblado 100"),
        (None, None),
    ]
    for entrada, esperado in casos:
        resultado = normalizar_direccion(entrada)
        assert resultado == esperado, f"Para '{entrada}' esperaba '{esperado}', obtuve '{resultado}'"
    print("✅ test_normalizar_direccion: PASS")


def test_clasificar_telefono():
    casos = [
        ("3001234567", "celular"),
        ("6044445566", "fijo"),
        ("6001234567", "fijo"),
        ("123456", "desconocido"),
    ]
    for tel, tipo in casos:
        resultado = clasificar_telefono(tel)
        assert resultado == tipo, f"Para '{tel}' esperaba '{tipo}', obtuve '{resultado}'"
    print("✅ test_clasificar_telefono: PASS")


if __name__ == "__main__":
    test_normalizar_nombre()
    test_normalizar_telefono()
    test_normalizar_correo()
    test_normalizar_direccion()
    test_clasificar_telefono()
    print("\n🎉 Todos los tests pasaron correctamente")
