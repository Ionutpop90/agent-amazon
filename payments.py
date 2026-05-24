import os
import stripe

stripe.api_key = os.environ.get("STRIPE_SECRET_KEY", "")

PRICE_ID = os.environ.get("STRIPE_PRICE_ID", "")

def create_checkout_session(user_email, success_url, cancel_url):
    try:
        session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=[{
                "price": PRICE_ID,
                "quantity": 1,
            }],
            mode="subscription",
            customer_email=user_email,
            success_url=success_url,
            cancel_url=cancel_url,
        )
        return True, session.url
    except Exception as e:
        return False, str(e)