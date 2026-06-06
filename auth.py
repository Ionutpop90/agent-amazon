import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from supabase import create_client

SUPABASE_URL = "https://mstwwbvvhzycswmlskjd.supabase.co"
SUPABASE_KEY = "sb_publishable_qC5hBcj_CvenVNyqFc5cRw_XIYbfrdI"

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

def send_welcome_email(email):
    try:
        gmail_user = os.environ.get("GMAIL_USER", "ionutpopionut9@gmail.com")
        gmail_pass = os.environ.get("GMAIL_PASSWORD", "jlljmdaahjpcodxq")

        print(f"Trimit email la: {email}")
        print(f"Gmail user: {gmail_user}")

        msg = MIMEMultipart('alternative')
        msg['Subject'] = "Bun venit la Agent Amazon! 🛒"
        msg['From'] = gmail_user
        msg['To'] = email

        html = """
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

        msg.attach(MIMEText(html, 'html'))
        server = smtplib.SMTP_SSL('smtp.gmail.com', 465)
        server.login(gmail_user, gmail_pass)
        server.sendmail(gmail_user, email, msg.as_string())
        server.quit()
        print("Email trimis cu succes!")
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