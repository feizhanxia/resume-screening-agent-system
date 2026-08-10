import asyncio
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from resume_agent.criteria.compiler import (
    compile_criteria_fast,
    decode_criteria_cache,
    encode_criteria_cache,
    heuristic_compile,
    jd_cache_fingerprint,
)
from resume_agent.domain.models import RunConfig
from resume_agent.llm.deepseek import (
    JD_MAX_ATTEMPTS,
    JD_MAX_TOKENS,
    JD_REQUEST_TIMEOUT_SECONDS,
    DeepSeekClient,
    ModelCallError,
)


def _response(content: str, finish_reason: str = "stop") -> SimpleNamespace:
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                finish_reason=finish_reason,
                message=SimpleNamespace(content=content),
            )
        ]
    )


VALID_CRITERIA = """{
  "criteria": [
    {
      "name": "Python能力",
      "definition": "熟练使用Python进行模型开发",
      "kind": "required",
      "requires_external_fact": false
    }
  ]
}"""


def test_jd_request_uses_dedicated_fast_parameters():
    client = DeepSeekClient("sk-test", RunConfig(timeout_seconds=120))
    requests = []
    attempts = []

    async def create(**kwargs):
        requests.append(kwargs)
        return _response(VALID_CRITERIA)

    client.client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create))
    )
    criteria = asyncio.run(
        client.compile_criteria(
            "要求精通 Python",
            "",
            on_attempt=lambda attempt, total: attempts.append((attempt, total)),
        )
    )

    assert len(requests) == 1
    assert attempts == [(1, JD_MAX_ATTEMPTS)]
    assert requests[0]["max_tokens"] == JD_MAX_TOKENS == 3_000
    assert requests[0]["timeout"] == JD_REQUEST_TIMEOUT_SECONDS == 18
    assert requests[0]["extra_body"] == {"thinking": {"type": "disabled"}}
    assert criteria[0].criterion_id.startswith("criterion.01.")
    assert criteria[0].weight == 15
    assert criteria[0].version == 2


def test_jd_request_retries_empty_and_invalid_schema_then_succeeds(monkeypatch):
    client = DeepSeekClient("sk-test", RunConfig())
    responses = iter([_response(""), _response('{"criteria":"bad"}'), _response(VALID_CRITERIA)])
    requests = []
    delays = []

    async def create(**kwargs):
        requests.append(kwargs)
        return next(responses)

    async def record_sleep(seconds):
        delays.append(seconds)

    client.client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create))
    )
    monkeypatch.setattr("resume_agent.llm.deepseek.asyncio.sleep", record_sleep)

    criteria = asyncio.run(client.compile_criteria("要求精通 Python", ""))

    assert len(criteria) == 1
    assert len(requests) == 3
    assert delays == [1.0, 2.0]


@pytest.mark.parametrize("status_code", [400, 401, 403])
def test_jd_request_does_not_retry_configuration_errors(monkeypatch, status_code):
    client = DeepSeekClient("sk-test", RunConfig())
    requests = []

    class ConfigurationFailure(RuntimeError):
        pass

    async def create(**kwargs):
        requests.append(kwargs)
        error = ConfigurationFailure("secret response must not be persisted")
        error.status_code = status_code
        raise error

    async def no_sleep(_seconds):
        raise AssertionError("authentication errors must not retry")

    client.client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create))
    )
    monkeypatch.setattr("resume_agent.llm.deepseek.asyncio.sleep", no_sleep)

    with pytest.raises(ModelCallError) as captured:
        asyncio.run(client.compile_criteria("要求精通 Python", ""))

    assert len(requests) == 1
    assert captured.value.diagnostics["http_status"] == status_code
    assert "secret response" not in str(captured.value)


def test_jd_request_retries_rate_limit_then_succeeds(monkeypatch):
    client = DeepSeekClient("sk-test", RunConfig())
    requests = []

    class RateLimited(RuntimeError):
        status_code = 429

    async def create(**kwargs):
        requests.append(kwargs)
        if len(requests) == 1:
            raise RateLimited("try later")
        return _response(VALID_CRITERIA)

    async def no_sleep(_seconds):
        return None

    client.client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create))
    )
    monkeypatch.setattr("resume_agent.llm.deepseek.asyncio.sleep", no_sleep)

    criteria = asyncio.run(client.compile_criteria("要求精通 Python", ""))

    assert criteria
    assert len(requests) == 2


def test_jd_total_timeout_returns_local_draft_and_cancels_request():
    cancelled = False

    class SlowClient:
        async def compile_criteria(self, _jd, _requirements, on_attempt=None):
            nonlocal cancelled
            if on_attempt:
                on_attempt(1, 3)
            try:
                await asyncio.sleep(60)
            except asyncio.CancelledError:
                cancelled = True
                raise

    outcome = asyncio.run(
        compile_criteria_fast(
            "要求精通 Python",
            "",
            SlowClient(),
            timeout_seconds=0.01,
        )
    )

    assert outcome.source == "local_draft"
    assert outcome.criteria
    assert outcome.warning == "TimeoutError"
    assert cancelled


def test_jd_cache_fingerprint_and_payload_are_safe_and_validated():
    jd = "任职要求\r\n精通 Python"
    criteria = heuristic_compile(jd)
    fingerprint = jd_cache_fingerprint(jd, "", "deepseek-v4-flash")

    assert fingerprint == jd_cache_fingerprint(
        "任职要求\n精通 Python", "", "deepseek-v4-flash"
    )
    assert fingerprint != jd_cache_fingerprint(jd, "", "another-model")
    assert jd not in fingerprint
    assert decode_criteria_cache(encode_criteria_cache(criteria)) == criteria
    with pytest.raises(ValueError):
        decode_criteria_cache("not-json")


def test_jd_qsettings_cache_hit_and_local_draft_status(monkeypatch, tmp_path: Path):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    try:
        from PySide6.QtCore import QSettings
        from PySide6.QtWidgets import QApplication

        from resume_agent.app.window import MainWindow
    except ImportError as exc:
        pytest.skip(f"Qt runtime is unavailable: {exc}")

    app = QApplication.instance() or QApplication([])
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    monkeypatch.setattr("resume_agent.app.window.QSettings", lambda: settings)
    window = MainWindow()
    jd = "要求精通 Python"
    criteria = heuristic_compile(jd)
    fingerprint = jd_cache_fingerprint(jd, "", window.config.model)
    window._save_criteria_cache(fingerprint, criteria)
    window.jd.setPlainText(jd)
    monkeypatch.setattr(
        "resume_agent.app.window.load_api_key",
        lambda: (_ for _ in ()).throw(AssertionError("cache hit must not load API key")),
    )

    window._compile_criteria()

    assert "已复用上次解析" in window.criteria_count.text()
    assert window.criteria_thread is None
    window._criteria_completed(criteria, "local_draft", "TimeoutError")
    assert "本地草稿，需人工确认" in window.criteria_count.text()
    assert window.criteria_count.toolTip() == "TimeoutError"
    window.close()
    app.processEvents()
