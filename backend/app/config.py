"""Settings read from the environment on every access (so tests can monkeypatch os.environ)."""
import os


def _b(name: str, default: str) -> bool:
    return os.environ.get(name, default).strip().lower() in ("1", "true", "yes", "on")


class Cfg:
    @property
    def db_path(self): return os.environ.get("DB_PATH", "./data/hisaabbol.db")
    @property
    def gnani_key(self): return os.environ.get("GNANI_API_KEY", "")
    @property
    def gnani_base(self): return os.environ.get("GNANI_BASE_URL", "https://api.vachana.ai")
    @property
    def stt_model(self): return os.environ.get("GNANI_STT_MODEL", "prisma-v3.0")
    @property
    def tts_model(self): return os.environ.get("GNANI_TTS_MODEL", "timbre-v3.0")
    @property
    def tts_voice(self): return os.environ.get("GNANI_TTS_VOICE", "Shivani")
    @property
    def gnani_concurrency(self): return int(os.environ.get("GNANI_CONCURRENCY", "1"))
    @property
    def gnani_mock(self): return _b("GNANI_MOCK", "false")
    @property
    def llm_provider(self): return os.environ.get("LLM_PROVIDER", "rules")
    @property
    def gemini_key(self): return os.environ.get("GEMINI_API_KEY", "")
    @property
    def gemini_model(self): return os.environ.get("GEMINI_MODEL", "")
    @property
    def registration_key(self): return os.environ.get("REGISTRATION_KEY", "")
    @property
    def demo_enabled(self): return _b("DEMO_ENABLED", "true")
    @property
    def rate_per_min(self): return int(os.environ.get("RATE_LIMIT_PER_MIN", "120"))
    @property
    def gnani_rate_per_min(self): return int(os.environ.get("GNANI_RATE_PER_MIN", "20"))
    @property
    def max_audio_bytes(self): return int(os.environ.get("MAX_AUDIO_BYTES", str(5 * 1024 * 1024)))

    @property
    def llm_enabled(self):
        return self.llm_provider == "gemini" and bool(self.gemini_key) and bool(self.gemini_model)


cfg = Cfg()
