# api/supa.py
import os
from supabase import create_client, Client
from dotenv import load_dotenv

# Load .env file if present (only affects local dev; Vercel ignores it)
load_dotenv()

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")

if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
    raise RuntimeError("Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY in env")

# This client is used only by the Flask server. Never expose the service-role
# key to browser code; it bypasses Supabase row-level security.
supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)
admin_client: Client = supabase
