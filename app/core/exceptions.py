"""Excepciones base de la aplicacion.

`AppError` es la raiz comun de todos los errores de dominio. Los servicios
lanzan subclases de cada modulo; los routers/orquestador las traducen a
respuestas HTTP o mensajes al usuario.
"""

from typing import Any


class AppError(Exception):
    """Error de aplicacion (dominio) con datos estructurados opcionales."""

    def __init__(self, message: str, *, data: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.data = data or {}
