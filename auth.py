import os
from supabase import create_client

SUPABASE_URL = "https://mstwwbvvhzycswmlskjd.supabase.co"
SUPABASE_KEY = "sb_publishable_qC5hBcj_CvenVNyqFc5cRw_XIYbfrdI"

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

def register_user(email, password):
    try:
        response = supabase.auth.sign_up({
            "email": email,
            "password": password
        })
        return True, "Cont creat cu succes!"
    except Exception as e:
        return False, str(e)

def login_user(email, password):
    try:
        response = supabase.auth.sign_in_with_password({
            "email": email,
            "password": password
        })
        return True, response.user
    except Exception as e:
        return False, str(e)