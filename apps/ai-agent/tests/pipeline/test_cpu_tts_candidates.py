"""Unit tests for IndicParlerTTSProvider and PiperTTSProvider — the two
CPU-friendly TTS candidates investigated after Qwen3-TTS/CosyVoice3 turned
out GPU-only. Covers metadata correctness (license fields must match
docs/MODEL_LICENSE_MATRIX.md exactly) and fail-closed error paths; none of
this requires downloading anything.
"""

import pytest

from app.pipeline.model_lifecycle import ModelNotAvailableError
from app.pipeline.tts import IndicParlerTTSProvider, PiperTTSProvider


@pytest.fixture
def allow_download(monkeypatch):
    monkeypatch.setenv("AI_ALLOW_MODEL_DOWNLOAD", "true")


def test_indic_parler_tts_metadata_reports_confirmed_clean_commercial_license():
    provider = IndicParlerTTSProvider()
    meta = provider.metadata()
    assert meta.code_license == "Apache-2.0"
    assert meta.weights_license == "Apache-2.0"
    assert meta.commercial_use is True
    assert meta.checkpoint == "ai4bharat/indic-parler-tts"


def test_indic_parler_tts_refuses_to_download_by_default():
    provider = IndicParlerTTSProvider()
    with pytest.raises(ModelNotAvailableError, match="AI_ALLOW_MODEL_DOWNLOAD"):
        provider.load()


def test_indic_parler_tts_synthesize_before_load_raises():
    provider = IndicParlerTTSProvider()
    with pytest.raises(RuntimeError, match="load"):
        provider.synthesize("hello", "en")


def test_piper_metadata_reports_unverified_voice_license_conservatively():
    """Real finding: the Piper ENGINE's license is fine (MIT archived /
    GPL-3.0 current, both safe via CLI-subprocess invocation), but the
    specific Tamil voice checkpoint's dataset license is unverified — the
    metadata must report commercial_use=False rather than assume it's
    fine just because the engine is permissively/copyleft licensed."""
    provider = PiperTTSProvider(checkpoint="/tmp/does-not-matter.onnx")
    meta = provider.metadata()
    assert meta.commercial_use is False
    assert "UNVERIFIED" in meta.weights_license


def test_piper_refuses_to_download_by_default():
    provider = PiperTTSProvider(checkpoint="/tmp/does-not-matter.onnx")
    with pytest.raises(ModelNotAvailableError, match="AI_ALLOW_MODEL_DOWNLOAD"):
        provider.load()


def test_piper_fails_closed_with_no_checkpoint_configured(allow_download):
    provider = PiperTTSProvider(checkpoint=None)
    with pytest.raises(ModelNotAvailableError, match="no local voice checkpoint"):
        provider.load()


def test_piper_fails_closed_when_executable_missing(allow_download):
    provider = PiperTTSProvider(checkpoint=__file__, piper_executable="definitely-not-a-real-binary-xyz")
    with pytest.raises(ModelNotAvailableError, match="executable was not found"):
        provider.load()


def test_piper_fails_closed_when_checkpoint_file_missing(allow_download):
    # A real executable-like name won't be found either in this sandbox,
    # but if the executable check somehow passed, the file-existence
    # check must also fail closed for a nonexistent checkpoint path.
    provider = PiperTTSProvider(checkpoint="/tmp/definitely-does-not-exist.onnx", piper_executable="echo")
    with pytest.raises(ModelNotAvailableError):
        provider.load()


def test_piper_never_imports_the_piper_python_package():
    """Real safety property: this class must invoke Piper only via CLI
    subprocess, never `import piper` into this process — that's the whole
    point of staying safe under the GPL-3.0 successor's copyleft terms.
    Parses the AST rather than substring-matching the source, since the
    class's own docstring mentions "import piper" in prose explaining
    this exact property."""
    import ast
    import inspect
    import textwrap

    source = textwrap.dedent(inspect.getsource(PiperTTSProvider))
    tree = ast.parse(source)
    imported_modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.add(node.module.split(".")[0])
    assert "piper" not in imported_modules
