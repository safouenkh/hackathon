"""Application settings, read from environment variables or the .env file."""
from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    postgres_host: str = "127.0.0.1"
    postgres_port: int = 5432
    postgres_db: str = "dalila"
    postgres_admin_user: str = "dalila_admin"
    postgres_admin_password: SecretStr = SecretStr("")
    postgres_ro_user: str = "dalila_ro"
    postgres_ro_password: SecretStr = SecretStr("")
    # Compte d'écriture : ajoute seulement les demandes envoyées et les besoins non couverts
    postgres_rw_user: str = "dalila_rw"
    postgres_rw_password: SecretStr = SecretStr("")
    afi_dump_path: str = "Chatbot Dalila/Dalila use case 1/afi.sql"
    # URL publique de base des fichiers zone_documents.fichier (inconnue au 26/11/2026 : vide = pas de lien)
    afi_documents_base_url: str = ""
    # Adresse publique du front (pages formulaire) ; vide = liens relatifs « /formulaire/... »
    frontend_base_url: str = ""
    # Ontologie (Turtle) : vide = ontology/afi_ontology.ttl du dépôt
    ontologie_path: str = ""
    # Index vectoriel des passages (Qdrant) et modèle d'embedding (BGE-M3, licence MIT)
    qdrant_url: str = "http://127.0.0.1:6333"
    qdrant_collection_passages: str = "passages_documents"
    embedding_model: str = "BAAI/bge-m3"
    embedding_device: str = ""            # vide : cuda:0 si disponible, sinon cpu
    qdrant_timeout_seconds: float = 5.0
    # Banc de test LLM (scripts/banc_llm_gemini.py) : clé jamais affichée ni committée
    gemini_api_key: SecretStr = SecretStr("")
    gemini_model: str = "gemini-flash-latest"
    gemini_fallback_models: str = ""      # modèles de repli, séparés par des virgules (surcharge 503, délai)
    llm_timeout_seconds: float = 30.0     # délai maximal par appel au LLM
    # Interface web du banc (/banc) : désactivée par défaut, jamais en production
    banc_llm_actif: bool = False

    # Service « langues et voix » (Dalila_Language, rôle 4) : vide = voix désactivée, réponse écrite seule.
    langue_url: str = ""                  # ex. http://127.0.0.1:7860
    langue_timeout_seconds: float = 60.0  # synthèse et reconnaissance tournent sur processeur

    def conninfo(self, admin: bool = False) -> str:
        """libpq connection string (key=value form, values are quoted by psycopg.conninfo)."""
        from psycopg.conninfo import make_conninfo

        user = self.postgres_admin_user if admin else self.postgres_ro_user
        password = self.postgres_admin_password if admin else self.postgres_ro_password
        return make_conninfo(
            host=self.postgres_host,
            port=self.postgres_port,
            dbname=self.postgres_db,
            user=user,
            password=password.get_secret_value(),
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
