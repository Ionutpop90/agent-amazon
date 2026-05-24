import os
import streamlit as st
import anthropic
import pandas as pd

client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

st.title("🛒 Agent Amazon - Casa Donostia")
st.write("Analiza automata a produselor cu AI")

st.header("Produsele tale")

produse = [
    {"nume": "Filtro TRICAPA", "vanzari": 500, "cheltuieli": 150, "rating": 3.7},
    {"nume": "Alcachofa Negra", "vanzari": 800, "cheltuieli": 200, "rating": 4.5},
    {"nume": "Alcachofa Cromo", "vanzari": 600, "cheltuieli": 180, "rating": 4.5},
]

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