"""Supabase client service for database operations."""
from supabase import create_client, Client
from config import Config


# Schema name for this project (isolates from other applications)
SCHEMA_NAME = "sifter_kys_dev"

_supabase_client: Client = None


def get_supabase_client() -> Client:
    """
    Get or create Supabase client instance.
    Uses service role key for backend operations (bypasses RLS).
    Configured to use the 'sifter_kys_dev' schema.
    """
    global _supabase_client

    if _supabase_client is None:
        if not Config.is_supabase_configured():
            raise RuntimeError(
                "Supabase is not configured. Set SUPABASE_URL and SUPABASE_SERVICE_KEY."
            )

        # Import ClientOptions here to handle potential import differences
        try:
            from supabase.lib.client_options import ClientOptions
            options = ClientOptions().replace(schema=SCHEMA_NAME)
        except ImportError:
            # Fallback for older versions - schema will be handled via API config
            options = None

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
