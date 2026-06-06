import os
import stripe
from auth import supabase

stripe.api_key = os.environ.get("STRIPE_SECRET_KEY", "")
PRICE_ID = os.environ.get("STRIPE_PRICE_ID", "")

def create_checkout_session(user_email, user_id, success_url, cancel_url):
    try:
        session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=[{
                "price": PRICE_ID,
                "quantity": 1,
            }],
            mode="subscription",
            customer_email=user_email,
            success_url=success_url + "&user_id=" + str(user_id),
            cancel_url=cancel_url,
        )
        return True, session.url
    except Exception as e:
        return False, str(e)

def activate_pro(user_id):
    try:
        existing = supabase.table("subscriptions").select("*").eq("user_id", user_id).execute()
        if len(existing.data) == 0:
            supabase.table("subscriptions").insert({
                "user_id": user_id,
                "is_pro": True
            }).execute()
        else:
            supabase.table("subscriptions").update({
                "is_pro": True
            }).eq("user_id", user_id).execute()
        return True
    except Exception as e:
        return False

def check_pro(user_id):
    try:
        result = supabase.table("subscriptions").select("is_pro").eq("user_id", user_id).execute()
        if len(result.data) > 0:
            return result.data[0]['is_pro']
        return False
    except:
        return False