"""Bounded, loopback-only Ollama transport. No remote inference fallback."""

from dataclasses import dataclass
from http.client import HTTPException
import json
import os
import socket
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

_UNSET = object()

class ModelError(Exception):
    """An actionable inference failure safe to display in the UI."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ModelSettings:
    base_url: str = "http://127.0.0.1:11434"
    model: str = "qwen2.5:3b"
    timeout: float = 120
    context_size: int = 4096
    output_tokens: int = 1200

    @classmethod
    def from_env(cls):
        try:
            settings = cls(
                base_url=os.environ.get("SAZON_OLLAMA_URL", cls.base_url).rstrip("/"),
                model=os.environ.get("SAZON_OLLAMA_MODEL", cls.model).strip(),
                timeout=float(os.environ.get("SAZON_OLLAMA_TIMEOUT", cls.timeout)),
                context_size=int(os.environ.get("SAZON_OLLAMA_CONTEXT", cls.context_size)),
                output_tokens=int(os.environ.get("SAZON_OLLAMA_OUTPUT_TOKENS", cls.output_tokens)),
            )
            settings.validate()
            return settings
        except (ValueError, TypeError) as error:
            raise ModelError("configuration", "Revisa la configuración local de Ollama.") from error

    def validate(self):
        url = urlsplit(self.base_url)
        if (url.scheme != "http" or url.hostname not in {"127.0.0.1", "localhost", "::1"}
                or url.username or url.password or url.path or url.query or url.fragment):
            raise ValueError("Ollama debe usar una dirección HTTP de loopback sin ruta.")
        if url.port is not None and not 1 <= url.port <= 65535:
            raise ValueError("Puerto no válido.")
        if (not self.model or "cloud" in self.model.casefold() or len(self.model) > 120 or not 1 <= self.timeout <= 180
                or not 2048 <= self.context_size <= 32768
                or not 256 <= self.output_tokens <= 4096):
            raise ValueError("Límites de inferencia no válidos.")


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class OllamaClient:
    def __init__(self, settings):
        settings.validate()
        self.settings = settings
        # Ignore system proxies and redirects: prompts stay on this machine.
        self.opener = build_opener(ProxyHandler({}), NoRedirects())
        self.thinking_mode = _UNSET

    def _discover_thinking(self):
        request = Request(
            self.settings.base_url + "/api/show",
            data=json.dumps({"model": self.settings.model}).encode(),
            headers={"Content-Type": "application/json"}, method="POST",
        )
        with self.opener.open(request, timeout=min(self.settings.timeout, 10)) as response:
            raw = response.read(262145)
        if len(raw) > 262144:
            raise ValueError("Metadatos locales demasiado grandes.")
        metadata = json.loads(raw)
        if not isinstance(metadata, dict):
            raise ValueError("Metadatos locales no válidos.")
        thinking = metadata.get("thinking")
        values = thinking.get("values", []) if isinstance(thinking, dict) else []
        if False in values:
            return False
        if True in values:
            return True
        # On older servers let the model use its default, with the native parser.
        return None

    def generate(self, messages, schema):
        payload = {
            "model": self.settings.model,
            "messages": messages,
            "format": schema,
            "stream": False,
            "keep_alive": "5m",
            "options": {
                "temperature": 0,
                "num_ctx": self.settings.context_size,
                "num_predict": self.settings.output_tokens,
            },
        }
        try:
            if self.thinking_mode is _UNSET:
                self.thinking_mode = self._discover_thinking()
            if self.thinking_mode is not None:
                payload["think"] = self.thinking_mode
            request = Request(
                self.settings.base_url + "/api/chat",
                data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                headers={"Content-Type": "application/json"}, method="POST",
            )
            with self.opener.open(request, timeout=self.settings.timeout) as response:
                raw = response.read(262145)
            if len(raw) > 262144:
                raise ModelError("invalid_response", "La respuesta local excedió el límite permitido.")
            envelope = json.loads(raw)
            if not isinstance(envelope, dict) or envelope.get("done") is not True:
                raise ValueError("Respuesta incompleta.")
            if envelope.get("done_reason") == "length":
                raise ValueError("Se agotó el límite de salida.")
            content = envelope["message"]["content"]
            if not isinstance(content, str):
                raise ValueError("Contenido no textual.")
            return json.loads(content)
        except HTTPError as error:
            if error.code == 404:
                raise ModelError("model_missing", "El modelo no está disponible. Descárgalo con ollama pull y vuelve a intentar.") from error
            raise ModelError("server_error", "Ollama no pudo completar la consulta. Revisa el servicio y el modelo local.") from error
        except (TimeoutError, socket.timeout) as error:
            raise ModelError("timeout", "El modelo tardó demasiado. Vuelve a intentar o configura un modelo más pequeño.") from error
        except URLError as error:
            if isinstance(error.reason, (TimeoutError, socket.timeout)):
                raise ModelError("timeout", "Se agotó el tiempo de espera del modelo local.") from error
            raise ModelError("unavailable", "Ollama no está disponible. Inicia Ollama en este equipo y vuelve a intentar.") from error
        except (ValueError, KeyError, TypeError, UnicodeError, RecursionError, HTTPException) as error:
            raise ModelError("invalid_response", "El modelo devolvió una respuesta incompleta o no válida. Vuelve a intentar.") from error
        except OSError as error:
            raise ModelError("unavailable", "No fue posible conectar con el servicio local de Ollama.") from error
