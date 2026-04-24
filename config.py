from dotenv import load_dotenv
import os

load_dotenv()


def get_env(name: str, default: str | None = None, required: bool = False) -> str | None:
    value = os.getenv(name, default)
    if required and not value:
        raise ValueError(f"Variável de ambiente obrigatória não encontrada: {name}")
    return value


DB_USER = get_env("SUPABASE_DB_USER", required=True)
DB_PASSWORD = get_env("SUPABASE_DB_PASSWORD", required=True)
DB_HOST = get_env("SUPABASE_DB_HOST", required=True)
DB_PORT = get_env("SUPABASE_DB_PORT", "5432")
DB_NAME = get_env("SUPABASE_DB_NAME", required=True)

TABLE_PREFIX = get_env("TABLE_PREFIX", "antt_")
CONTROL_PREFIX = get_env("CONTROL_PREFIX", "antt_antt_")
APP_TITLE = get_env("APP_TITLE", "Dashboard ANTT")