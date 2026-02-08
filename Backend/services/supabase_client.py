"""Supabase client service for database operations."""
from supabase import create_client, Client, ClientOptions
from config import Config


# Schema name for this project (isolates from other applications)
SCHEMA_NAME = "sifter_dev"

_supabase_client: Client = None


def get_supabase_client() -> Client:
    """
    Get or create Supabase client instance.
    Uses service role key for backend operations (bypasses RLS).
    Configured to use the 'sifter_dev' schema.
    """
    global _supabase_client

    if _supabase_client is None:
        if not Config.is_supabase_configured():
            raise RuntimeError(
                "Supabase is not configured. Set SUPABASE_URL and SUPABASE_SERVICE_KEY."
            )

        # Use ClientOptions with schema for database isolation
        options = ClientOptions(schema=SCHEMA_NAME)

        _supabase_client = create_client(
            Config.SUPABASE_URL,
            Config.SUPABASE_SERVICE_KEY,
            options=options
        )
        print(f"[SUPABASE] Client initialized with schema '{SCHEMA_NAME}'")

    return _supabase_client


def is_supabase_available() -> bool:
    """Check if Supabase is configured and available."""
    return Config.is_supabase_configured()


def get_schema_name() -> str:
    """Return the schema name used by this project."""
    return SCHEMA_NAME
