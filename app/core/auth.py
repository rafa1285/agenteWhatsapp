"""Validador JWT RS256 para autenticación panel → backend.

El panel (Laravel) firma tokens con su clave privada; el backend valida
con la clave pública compartida. El token debe contener:
- `restaurant_id` (UUID del tenant)
- `iss` = JWT_ISSUER
- `aud` = JWT_AUDIENCE
- `exp` / `iat` estándar
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import jwt

from app.core.settings import settings


@dataclass(frozen=True, slots=True)
class TokenPayload:
    """Claims válidos extraídos del JWT."""
    restaurant_id: str
    iss: str
    aud: str
    exp: int
    iat: int
    raw: dict[str, Any]


class JWTValidationError(Exception):
    """Excepción base para errores de validación JWT."""
    pass


class JWTExpiredError(JWTValidationError):
    """Token expirado."""
    pass


class JWTInvalidSignatureError(JWTValidationError):
    """Firma inválida o clave incorrecta."""
    pass


class JWTInvalidClaimsError(JWTValidationError):
    """Claims requeridos ausentes o inválidos."""
    pass


def load_public_key() -> str:
    """Carga la clave pública PEM desde `settings.JWT_PUBLIC_KEY_PATH`."""
    path = Path(settings.JWT_PUBLIC_KEY_PATH)
    if not path.is_file():
        raise FileNotFoundError(
            f"Clave pública JWT no encontrada en {path}. "
            "Genera par RSA: openssl genrsa -out private.pem 2048 && "
            "openssl rsa -in private.pem -pubout -out public.pem"
        )
    return path.read_text(encoding="utf-8")


_PUBLIC_KEY_CACHE: str | None = None


def get_public_key() -> str:
    """Clave pública cacheada (se recarga si cambia el archivo en dev)."""
    global _PUBLIC_KEY_CACHE
    if _PUBLIC_KEY_CACHE is None:
        _PUBLIC_KEY_CACHE = load_public_key()
    return _PUBLIC_KEY_CACHE


def validate_token(token: str) -> TokenPayload:
    """
    Valida un JWT RS256 y devuelve sus claims tipados.

    Lanza:
    - `JWTExpiredError` si `exp` pasó
    - `JWTInvalidSignatureError` si firma no verifica
    - `JWTInvalidClaimsError` si claims requeridos faltan o no coinciden
    """
    try:
        public_key = get_public_key()
        payload = jwt.decode(
            token,
            public_key,
            algorithms=[settings.JWT_ALGORITHM],
            issuer=settings.JWT_ISSUER,
            audience=settings.JWT_AUDIENCE,
            options={"require": ["exp", "iat", "iss", "aud", "restaurant_id"]},
        )
    except jwt.ExpiredSignatureError as e:
        raise JWTExpiredError("Token expirado") from e
    except jwt.InvalidSignatureError as e:
        raise JWTInvalidSignatureError("Firma inválida") from e
    except jwt.InvalidAudienceError as e:
        raise JWTInvalidClaimsError(f"Audience inválido: {e}") from e
    except jwt.InvalidIssuerError as e:
        raise JWTInvalidClaimsError(f"Issuer inválido: {e}") from e
    except jwt.MissingRequiredClaimError as e:
        raise JWTInvalidClaimsError(f"Claim requerido ausente: {e}") from e
    except jwt.PyJWTError as e:
        raise JWTValidationError(f"Token inválido: {e}") from e

    restaurant_id = payload.get("restaurant_id")
    if not restaurant_id:
        raise JWTInvalidClaimsError("Claim 'restaurant_id' requerido")

    return TokenPayload(
        restaurant_id=restaurant_id,
        iss=payload["iss"],
        aud=payload["aud"],
        exp=payload["exp"],
        iat=payload["iat"],
        raw=payload,
    )


def invalidate_cache() -> None:
    """Invalida caché de clave pública (útil en tests o rotación de claves)."""
    global _PUBLIC_KEY_CACHE
    _PUBLIC_KEY_CACHE = None
