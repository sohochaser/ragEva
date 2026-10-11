"""A bounded Chat Completions probe before saving an online model."""

import json

import httpx


class ModelValidationError(Exception):
    pass


def probe_online_model(
    client: httpx.Client,
    base_url: str,
    model_name: str,
    token: str | None,
    timeout_seconds: float,
) -> None:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    try:
        response = client.post(
            base_url.rstrip("/") + "/chat/completions",
            headers=headers,
            json={
                "model": model_name,
                "messages": [
                    {"role": "system", "content": "Return only a JSON object."},
                    {"role": "user", "content": '{"probe":"Return a short JSON object"}'},
                ],
                "temperature": 0,
                "response_format": {"type": "json_object"},
            },
            timeout=timeout_seconds,
        )
    except httpx.TimeoutException as exc:
        raise ModelValidationError("model_timeout") from exc
    except httpx.TransportError as exc:
        raise ModelValidationError("model_connection_error") from exc
    if not 200 <= response.status_code < 300:
        raise ModelValidationError(f"model_http_{response.status_code}")
    try:
        payload = response.json()
        content = payload["choices"][0]["message"]["content"]
        result = json.loads(content)
        if not isinstance(result, dict):
            raise ValueError("JSON object required")
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise ModelValidationError("invalid_model_response") from exc
