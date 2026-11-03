import httpx

from app.core.config import get_settings
from app.schemas.requests import GenerateRequest


class OllamaUnavailable(Exception):
    pass


async def list_models():
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            response = await client.get(f"{get_settings().ollama_base_url}/api/tags")
            response.raise_for_status()
            return {"available": True, "models": response.json().get("models", [])}
    except (httpx.HTTPError, ValueError):
        return {"available": False, "models": [], "message": "Cannot connect to Ollama"}


def decoding_schema(schema):
    """Keep structural grammar small; callers validate full semantic bounds with Pydantic.

    Ollama 0.13's grammar generator can crash with high maxLength repetitions.
    """
    ignored = {
        "minLength",
        "maxLength",
        "minItems",
        "maxItems",
        "minimum",
        "maximum",
        "exclusiveMinimum",
        "exclusiveMaximum",
        "multipleOf",
    }
    if isinstance(schema, dict):
        return {k: decoding_schema(v) for k, v in schema.items() if k not in ignored}
    if isinstance(schema, list):
        return [decoding_schema(v) for v in schema]
    return schema


async def generate(payload: GenerateRequest):
    try:
        async with httpx.AsyncClient(timeout=get_settings().ollama_timeout_seconds) as client:
            response = await client.post(
                f"{get_settings().ollama_base_url}/api/generate",
                json={
                    "model": payload.model,
                    "prompt": payload.prompt,
                    "system": payload.system,
                    "stream": False,
                    **(
                        {"format": decoding_schema(payload.format)}
                        if payload.format is not None
                        else {}
                    ),
                    "options": {
                        "temperature": payload.temperature,
                        "num_predict": payload.max_tokens,
                        "seed": payload.seed,
                    },
                },
            )
            response.raise_for_status()
            data = response.json()
            if "error" in data or not isinstance(data.get("response"), str):
                raise OllamaUnavailable("Ollama returned an invalid response")
            return data
    except httpx.TimeoutException as exc:
        raise OllamaUnavailable(
            "Model request timed out. Try fewer output tokens or a smaller model."
        ) from exc
    except (httpx.HTTPError, ValueError) as exc:
        raise OllamaUnavailable(
            "Ollama request failed. Check the service and installed model."
        ) from exc
