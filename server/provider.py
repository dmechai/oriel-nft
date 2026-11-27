from __future__ import annotations

import base64
import re
from typing import Any

import httpx

from .crypto import decrypt


class ProviderError(RuntimeError):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


def _join(base_url: str, path: str) -> str:
    return base_url.rstrip("/") + "/" + path.lstrip("/")


def _error_message(response: httpx.Response) -> str:
    try:
        body = response.json()
    except Exception:
        body = {}
    if isinstance(body, dict):
        err = body.get("error")
        if isinstance(err, dict) and err.get("message"):
            return str(err["message"])
        if body.get("message"):
            return str(body["message"])
    text = response.text.strip()
    return text[:400] or f"上游返回 {response.status_code}"


def message_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, dict):
                parts.append(str(part.get("text") or part.get("content") or ""))
        return "\n".join(part for part in parts if part)
    return str(content or "")


def extract_json_object(text: str) -> dict:
    import json

    raw = text.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", raw, re.S)
    if fenced:
        raw = fenced.group(1)
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end <= start:
        raise ProviderError("模型没有返回可解析的 JSON")
    try:
        data = json.loads(raw[start : end + 1])
    except json.JSONDecodeError as exc:
        raise ProviderError("模型返回的 JSON 无法解析") from exc
    if not isinstance(data, dict):
        raise ProviderError("模型返回的不是 JSON 对象")
    return data


def _bytes_from_data_url(url: str) -> bytes | None:
    match = re.match(r"data:image/[^;]+;base64,(.+)", url, re.S)
    if not match:
        return None
    return base64.b64decode(match.group(1))


def extract_image_bytes(payload: Any) -> bytes:
    if isinstance(payload, dict):
        data = payload.get("data")
        if isinstance(data, list) and data:
            item = data[0]
            if isinstance(item, dict):
                if item.get("b64_json"):
                    return base64.b64decode(item["b64_json"])
                if item.get("url"):
                    return _download(item["url"])
        choices = payload.get("choices") or []
        if choices:
            message = (choices[0] or {}).get("message") or {}
            found = _image_from_message(message)
            if found:
                return found
        for key in ("b64_json", "image"):
            if isinstance(payload.get(key), str) and len(payload[key]) > 80:
                try:
                    return base64.b64decode(payload[key])
                except Exception:
                    pass
    raise ProviderError("上游响应里没有找到图片")


def _image_from_message(message: dict) -> bytes | None:
    content = message.get("content")
    blobs = []
    if isinstance(content, list):
        blobs.extend(content)
    if isinstance(message.get("images"), list):
        blobs.extend(message["images"])
    for part in blobs:
        if not isinstance(part, dict):
            continue
        url = ""
        image_url = part.get("image_url")
        if isinstance(image_url, dict):
            url = image_url.get("url") or ""
        elif isinstance(image_url, str):
            url = image_url
        url = url or part.get("url") or ""
        if url.startswith("data:image"):
            found = _bytes_from_data_url(url)
            if found:
                return found
        if url.startswith("http"):
            return _download(url)
        b64 = part.get("b64_json") or part.get("data")
        if isinstance(b64, str) and len(b64) > 80:
            try:
                return base64.b64decode(b64)
            except Exception:
                pass
    text = message_text(content)
    data_url = re.search(r"data:image/[a-zA-Z0-9.+-]+;base64,[A-Za-z0-9+/=\s]+", text)
    if data_url:
        return _bytes_from_data_url(data_url.group(0).replace("\n", ""))
    markdown = re.search(r"!\[[^\]]*\]\((https?://[^)]+)\)", text)
    if markdown:
        return _download(markdown.group(1))
    return None


def _download(url: str) -> bytes:
    response = httpx.get(url, timeout=60, follow_redirects=True)
    if response.status_code >= 400:
        raise ProviderError(f"下载生成图片失败：{response.status_code}", response.status_code)
    return response.content


class ProviderClient:
    def __init__(self, row: dict):
        self.base_url = row["base_url"].rstrip("/")
        self.api_key = decrypt(row["api_key_enc"]) if row["api_key_enc"] else ""
        self.edit_model = row.get("edit_model") or row.get("image_model") or ""
        self.image_api = row.get("image_api") or "openai_images"
        self.vision_model = row.get("vision_model") or ""
        self.text_model = row.get("text_model") or ""
        self.image_model = row.get("image_model") or ""

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}

    def _error(self, response: httpx.Response) -> str:
        message = _error_message(response)
        return message.replace(self.api_key, "[已隐藏]") if self.api_key else message

    def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        timeout = kwargs.pop("timeout", 120)
        last_error: Exception | None = None
        for attempt in range(2):
            try:
                response = httpx.request(method, _join(self.base_url, path), headers=self._headers(), timeout=timeout, **kwargs)
            except httpx.HTTPError as exc:
                last_error = exc
                if attempt == 0:
                    continue
                raise ProviderError(f"无法连接接口：{exc}") from exc
            if response.status_code in (429, 502, 503, 504) and attempt == 0:
                continue
            return response
        raise ProviderError(f"无法连接接口：{last_error}")

    def list_models(self) -> list[str]:
        response = self._request("GET", "/models", timeout=30)
        if response.status_code >= 400:
            raise ProviderError(self._error(response), response.status_code)
        body = response.json()
        rows = body.get("data") if isinstance(body, dict) else None
        if rows is None and isinstance(body, dict):
            rows = body.get("models")
        names = []
        for row in rows or []:
            if isinstance(row, str):
                names.append(row)
            elif isinstance(row, dict) and row.get("id"):
                names.append(str(row["id"]))
        if not names:
            raise ProviderError("上游没有返回模型列表，可以手动填写模型名")
        return names

    def chat(self, model: str, messages: list[dict], temperature: float = 0.4) -> str:
        if not model:
            raise ProviderError("还没有选择模型")
        response = self._request(
            "POST",
            "/chat/completions",
            json={"model": model, "messages": messages, "temperature": temperature},
            timeout=180,
        )
        if response.status_code >= 400:
            raise ProviderError(self._error(response), response.status_code)
        body = response.json()
        try:
            content = body["choices"][0]["message"]["content"]
        except Exception as exc:
            raise ProviderError("对话接口没有返回文本") from exc
        return message_text(content)

    def ping(self) -> str:
        model = self.text_model or self.vision_model
        text = self.chat(model, [{"role": "user", "content": "Reply with the single word OK."}], temperature=0)
        return text.strip()[:80]

    def image_from_reference(self, prompt: str, size: str, reference: bytes | None, mime: str = "image/png", *, require_reference: bool = False) -> tuple[bytes, bool]:
        if require_reference and not reference:
            raise ProviderError("参考图编辑需要提供图片")
        model = self.edit_model if reference else self.image_model
        if not model:
            raise ProviderError("请设置图像编辑或图像生成模型")
        if self.image_api == "chat_image":
            if reference:
                return self._chat_image(prompt, reference, mime), True
            return self._chat_image(prompt, None, mime), False
        if reference:
            try:
                return self._openai_edit(prompt, size, reference, mime), True
            except ProviderError as exc:
                message = str(exc).lower()
                unsupported = exc.status in (404, 405, 501) or (
                    exc.status in (400, 422) and any(token in message for token in ("not supported", "unsupported"))
                )
                if not unsupported:
                    raise
                if require_reference or not self.image_model:
                    raise ProviderError(f"当前接口或模型不支持参考图编辑：{exc}", exc.status) from exc
        return self._openai_generate(prompt, size), False

    def _openai_generate(self, prompt: str, size: str) -> bytes:
        payload = {"model": self.image_model, "prompt": prompt, "size": size, "n": 1, "response_format": "b64_json"}
        response = self._request("POST", "/images/generations", json=payload, timeout=240)
        if response.status_code >= 400 and "response_format" in _error_message(response).lower():
            payload.pop("response_format", None)
            response = self._request("POST", "/images/generations", json=payload, timeout=240)
        if response.status_code >= 400:
            raise ProviderError(self._error(response), response.status_code)
        return extract_image_bytes(response.json())

    def _openai_edit(self, prompt: str, size: str, reference: bytes, mime: str) -> bytes:
        files = {"image": ("reference.png", reference, mime)}
        data = {"model": self.edit_model, "prompt": prompt, "size": size, "response_format": "b64_json"}
        response = self._request("POST", "/images/edits", data=data, files=files, timeout=240)
        if response.status_code >= 400 and "response_format" in _error_message(response).lower():
            data.pop("response_format", None)
            response = self._request("POST", "/images/edits", data=data, files=files, timeout=240)
        if response.status_code >= 400:
            raise ProviderError(self._error(response), response.status_code)
        return extract_image_bytes(response.json())

    def _chat_image(self, prompt: str, reference: bytes | None, mime: str) -> bytes:
        content: list[dict] = [{"type": "text", "text": prompt}]
        if reference:
            encoded = base64.b64encode(reference).decode()
            content.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{encoded}"}})
        payload = {
            "model": self.edit_model if reference else self.image_model,
            "messages": [{"role": "user", "content": content}],
            "modalities": ["image", "text"],
        }
        response = self._request("POST", "/chat/completions", json=payload, timeout=240)
        if response.status_code >= 400 and "modalit" in _error_message(response).lower():
            payload.pop("modalities", None)
            response = self._request("POST", "/chat/completions", json=payload, timeout=240)
        if response.status_code >= 400:
            raise ProviderError(self._error(response), response.status_code)
        return extract_image_bytes(response.json())
