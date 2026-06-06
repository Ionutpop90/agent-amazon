import os
from supabase import create_client
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail

SUPABASE_URL = "https://mstwwbvvhzycswmlskjd.supabase.co"
SUPABASE_KEY = "sb_publishable_qC5hBcj_CvenVNyqFc5cRw_XIYbfrdI"

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

def send_welcome_email(email):
    try:
        sg_key = os.environ.get("SENDGRID_API_KEY", "")
        print(f"Trimit email la: {email}")

        message = Mail(
            from_email="ionutpopionut9@gmail.com",
            to_emails=email,
            subject="Bun venit la Agent Amazon! 🛒",
            html_content="""
            <h2>Bun venit la Agent Amazon! 🛒</h2>
            <p>Contul tau a fost creat cu succes.</p>
            <p>Acum poti:</p>
            <ul>
            <li>✅ Adauga produsele tale Amazon</li>
            <li>✅ Analiza ACOS-ul automat</li>
            <li>✅ Primi recomandari AI zilnice</li>
            </ul>
            <a href="https://agent-amazon-production.up.railway.app">Acceseaza aplicatia →</a>
            """
        )

        sg = SendGridAPIClient(sg_key)
        response = sg.send(message)
        print(f"Email trimis! Status: {response.status_code}")
        return True
    except Exception as e:
        print(f"EROARE EMAIL: {e}")
        return False

def register_user(email, password):
    try:
        response = supabase.auth.sign_up({
            "email": email,
            "password": password
        })
        send_welcome_email(email)
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