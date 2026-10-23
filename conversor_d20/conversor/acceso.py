"""Pantalla de acceso con contraseña (simple).

La contraseña se lee de st.secrets["password"] (Streamlit Cloud: Settings > Secrets) o de la variable de
entorno APP_PASSWORD. Si no hay ninguna configurada, la app NO se abre (falla cerrada), salvo que se defina
APP_SIN_LOGIN=1 (lo usa iniciar.bat para el uso local en la propia computadora).
"""
from __future__ import annotations

import hmac
import os
import time

import streamlit as st

MAX_INTENTOS = 5


def _password_configurada() -> str | None:
    try:
        if "password" in st.secrets:
            return str(st.secrets["password"])
    except Exception:  # noqa: BLE001 - no hay secrets.toml
        pass
    return os.environ.get("APP_PASSWORD") or None


def requerir_login() -> None:
    """Detiene la ejecución de la página hasta que el usuario ingrese la contraseña correcta."""
    if os.environ.get("APP_SIN_LOGIN") == "1":
        return
    if st.session_state.get("autenticado"):
        with st.sidebar:
            if st.button("Cerrar sesión"):
                for k in list(st.session_state.keys()):
                    del st.session_state[k]
                st.rerun()
        return

    clave = _password_configurada()
    st.title("Conversor de Remuneraciones — Nacional Software a IPS D20 Digital")
    if not clave:
        st.error("La aplicación no tiene contraseña configurada. Definí `password` en Secrets "
                 "(Streamlit Cloud) o en `.streamlit/secrets.toml`.")
        st.stop()

    intentos = st.session_state.get("intentos", 0)
    if intentos >= MAX_INTENTOS:
        st.error("Demasiados intentos fallidos. Cerrá y volvé a abrir la página.")
        st.stop()
    with st.form("login"):
        ingreso = st.text_input("Contraseña", type="password")
        entrar = st.form_submit_button("Ingresar")
    if entrar:
        if hmac.compare_digest(ingreso.encode(), clave.encode()):
            st.session_state["autenticado"] = True
            st.session_state["intentos"] = 0
            st.rerun()
        st.session_state["intentos"] = intentos + 1
        time.sleep(1)
        st.error("Contraseña incorrecta.")
    st.stop()
