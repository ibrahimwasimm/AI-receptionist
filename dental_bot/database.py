import os
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL: str = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY: str = os.getenv("SUPABASE_KEY", "")

# Singleton Supabase client — import this everywhere instead of creating new clients
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
