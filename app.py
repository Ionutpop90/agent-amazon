import os
import streamlit as st
import anthropic
import pandas as pd
from auth import register_user, login_user, supabase

api_key = os.environ.get("ANTHROPIC_API_KEY", "")
client = anthropic.Anthropic(api_key=api_key)

st.title("🛒 Agent Amazon - Casa Donostia")

if 'logged_in' not in st.session_state:
    st.session_state.logged_in = False
if 'user' not in st.session_state:
    st.session_state.user = None

if not st.session_state.logged_in:
    st.header("Login / Register")
    tab1, tab2 = st.tabs(["Login", "Register"])
    with tab1:
        email = st.text_input("Email", key="login_email")
        password = st.text_input("Parola", type="password", key="login_pass")
        if st.button("Login"):
            success, result = login_user(email, password)
            if success:
                st.session_state.logged_in = True
                st.session_state.user = result
                st.rerun()
            else:
                st.error("Email sau parola gresite!")
    with tab2:
        email_reg = st.text_input("Email", key="reg_email")
        password_reg = st.text_input("Parola", type="password", key="reg_pass")
        if st.button("Creaza cont"):
            success, message = register_user(email_reg, password_reg)
            if success:
                st.success(message)
            else:
                st.error(message)
else:
    st.write(f"Bun venit! {st.session_state.user.email}")
    if st.button("Logout"):
        st.session_state.logged_in = False
        st.session_state.user = None
        st.rerun()

    st.header("Produsele tale")

    with st.expander("➕ Adauga produs nou"):
        nume = st.text_input("Nume produs")
        vanzari = st.number_input("Vanzari lunare (€)", min_value=0)
        cheltuieli = st.number_input("Cheltuieli publicitate (€)", min_value=0)
        rating = st.number_input("Rating", min_value=0.0, max_value=5.0, step=0.1)
        if st.button("💾 Salveaza produs"):
            supabase.table("produse").insert({
                "user_id": st.session_state.user.id,
                "nume": nume,
                "vanzari": vanzari,
                "cheltuieli": cheltuieli,
                "rating": rating
            }).execute()
            st.success("Produs salvat!")
            st.rerun()

    result = supabase.table("produse").select("*").eq("user_id", st.session_state.user.id).execute()
    produse = result.data

    if len(produse) == 0:
        st.info("Nu ai produse adaugate inca. Adauga primul produs!")
    else:
        df = pd.DataFrame(produse)
        st.dataframe(df)

        if st.button("🔍 Analizeaza produsele"):
            st.header("Rezultate analiza")
            for produs in produse:
                acos = (produs['cheltuieli'] / produs['vanzari']) * 100
                with st.expander(f"📦 {produs['nume']} — ACOS {acos:.1f}%"):
                    if produs['rating'] < 4.0:
                        st.warning(f"⚠️ Rating slab: {produs['rating']}")
                        with st.spinner("Claude analizeaza..."):
                            mesaj = client.messages.create(
                                model="claude-haiku-4-5-20251001",
                                max_tokens=150,
                                messages=[
                                    {"role": "user", "content": f"2 actiuni concrete pentru '{produs['nume']}' cu rating {produs['rating']}: "}
                                ]
                            )
                            st.write(mesaj.content[0].text)
                    else:
                        st.success(f"✅ Rating bun: {produs['rating']}")

    st.header("Analiza Reviewuri")
    fisier = st.file_uploader("Incarca CSV cu reviewuri", type="csv")
    if fisier is not None:
        df_reviews = pd.read_csv(fisier)
        st.write(f"Reviewuri incarcate: {len(df_reviews)}")
        st.dataframe(df_reviews)
        if st.button("🤖 Analizeaza reviewurile negative"):
            negative = df_reviews[df_reviews['rating'] <= 2]
            st.write(f"Reviewuri negative gasite: {len(negative)}")
            for index, row in negative.iterrows():
                with st.expander(f"⚠️ {row['produs']} — {row['review'][:50]}..."):
                    with st.spinner("Claude analizeaza..."):
                        mesaj = client.messages.create(
                            model="claude-haiku-4-5-20251001",
                            max_tokens=150,
                            messages=[
                                {"role": "user", "content": f"Solutie concreta in 2 randuri pentru acest review negativ: '{row['review']}'"}
                            ]
                        )
                        st.write(mesaj.content[0].text)