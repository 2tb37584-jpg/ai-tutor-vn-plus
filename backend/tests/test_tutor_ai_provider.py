from types import SimpleNamespace

from app.services import tutor_ai


class FakeOpenAI:
    calls: list[dict[str, str]] = []

    def __init__(self, **kwargs: str):
        self.kwargs = kwargs
        type(self).calls.append(kwargs)


def _settings(*, api_key: str = "test-key", base_url: str = "", model: str = "test-model"):
    return SimpleNamespace(
        openai_api_key=api_key,
        openai_base_url=base_url,
        openai_model=model,
    )


def _build_tutor(monkeypatch, settings):
    FakeOpenAI.calls = []
    monkeypatch.setattr(tutor_ai, "OpenAI", FakeOpenAI)
    monkeypatch.setattr(tutor_ai, "get_settings", lambda: settings)
    return tutor_ai.TutorAI()


def test_no_api_key_keeps_demo_mode_without_constructing_client(monkeypatch):
    tutor = _build_tutor(
        monkeypatch,
        _settings(api_key="", base_url="https://provider.example/v1"),
    )

    assert tutor.client is None
    assert FakeOpenAI.calls == []


def test_empty_base_url_uses_default_openai_endpoint(monkeypatch):
    tutor = _build_tutor(monkeypatch, _settings())

    assert isinstance(tutor.client, FakeOpenAI)
    assert FakeOpenAI.calls == [{"api_key": "test-key"}]


def test_whitespace_only_base_url_uses_default_openai_endpoint(monkeypatch):
    tutor = _build_tutor(monkeypatch, _settings(base_url="   "))

    assert isinstance(tutor.client, FakeOpenAI)
    assert FakeOpenAI.calls == [{"api_key": "test-key"}]


def test_custom_base_url_is_passed_to_openai_client(monkeypatch):
    tutor = _build_tutor(
        monkeypatch,
        _settings(base_url="https://provider.example/v1"),
    )

    assert isinstance(tutor.client, FakeOpenAI)
    assert FakeOpenAI.calls == [
        {
            "api_key": "test-key",
            "base_url": "https://provider.example/v1",
        }
    ]


def test_custom_base_url_is_stripped_without_mutating_model(monkeypatch):
    settings = _settings(
        base_url="  https://provider.example/v1  ",
        model="provider-model",
    )
    _build_tutor(monkeypatch, settings)

    assert FakeOpenAI.calls == [
        {
            "api_key": "test-key",
            "base_url": "https://provider.example/v1",
        }
    ]
    assert settings.openai_model == "provider-model"
