import os
import streamlit as st
import anthropic
import pandas as pd
import plotly.express as px
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage
from auth import register_user, login_user, supabase
from payments import create_checkout_session, activate_pro, check_pro

st.set_page_config(
    page_title="Agent Amazon",
    page_icon="🛒",
    layout="wide"
)

api_key = os.environ.get("ANTHROPIC_API_KEY", "")
client = anthropic.Anthropic(api_key=api_key)

if 'logged_in' not in st.session_state:
    st.session_state.logged_in = False
if 'user' not in st.session_state:
    st.session_state.user = None
if 'pagina' not in st.session_state:
    st.session_state.pagina = "Dashboard"

if not st.session_state.logged_in:
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.title("🛒 Agent Amazon")
        st.write("Analiza automata a produselor cu AI")
        tab1, tab2 = st.tabs(["🔑 Login", "📝 Register"])
        with tab1:
            email = st.text_input("Email", key="login_email")
            password = st.text_input("Parola", type="password", key="login_pass")
            if st.button("Login", use_container_width=True):
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
            if st.button("Creaza cont", use_container_width=True):
                success, message = register_user(email_reg, password_reg)
                if success:
                    st.success(message)
                else:
                    st.error(message)
else:
    with st.sidebar:
        st.title("🛒 Agent Amazon")
        st.write(f"👤 {st.session_state.user.email}")
        st.divider()

        st.markdown("### Navigare")
        if st.button("📊  Dashboard", use_container_width=True):
            st.session_state.pagina = "Dashboard"
        if st.button("📦  Produse", use_container_width=True):
            st.session_state.pagina = "Produse"
        if st.button("💬  Reviewuri", use_container_width=True):
            st.session_state.pagina = "Reviewuri"
        if st.button("🤖  Agent AI", use_container_width=True):
            st.session_state.pagina = "Agent"

        st.divider()

        is_pro = check_pro(st.session_state.user.id)

        if is_pro:
            st.success("⭐ Plan Pro Activ")
        else:
            st.info("🆓 Plan Gratuit\n2 produse maxim")
            if st.button("⭐ Upgrade Pro — 29€/lună", use_container_width=True):
                success, url = create_checkout_session(
                    st.session_state.user.email,
                    st.session_state.user.id,
                    success_url="https://agent-amazon-production.up.railway.app?success=true",
                    cancel_url="https://agent-amazon-production.up.railway.app?cancel=true"
                )
                if success:
                    st.markdown(f"[👉 Plateste aici]({url})")

        st.divider()
        if st.button("🚪 Logout", use_container_width=True):
            st.session_state.logged_in = False
            st.session_state.user = None
            st.rerun()

    if "success" in st.query_params:
        activate_pro(st.session_state.user.id)
        st.success("🎉 Plan Pro activat!")

    result = supabase.table("produse").select("*").eq("user_id", st.session_state.user.id).execute()
    produse = result.data
    pagina = st.session_state.pagina

    if pagina == "Dashboard":
        st.title("📊 Dashboard")
        if len(produse) == 0:
            st.info("Nu ai produse adaugate inca. Mergi la sectiunea Produse!")
        else:
            col1, col2, col3 = st.columns(3)
            acos_list = [(p['cheltuieli'] / p['vanzari']) * 100 for p in produse]
            with col1:
                st.metric("Total Produse", len(produse))
            with col2:
                st.metric("ACOS Mediu", f"{sum(acos_list)/len(acos_list):.1f}%")
            with col3:
                rating_mediu = sum(p['rating'] for p in produse) / len(produse)
                st.metric("Rating Mediu", f"{rating_mediu:.1f} ⭐")

            st.divider()
            st.subheader("Situatie produse")
            df = pd.DataFrame(produse)
            df['ACOS %'] = df.apply(lambda r: (r['cheltuieli']/r['vanzari'])*100, axis=1)
            st.dataframe(df[['nume', 'vanzari', 'cheltuieli', 'rating', 'ACOS %']], use_container_width=True)

            st.divider()
            st.subheader("📈 Grafic ACOS per produs")
            fig_acos = px.bar(
                df, x='nume', y='ACOS %',
                color='ACOS %',
                color_continuous_scale=['green', 'yellow', 'red'],
                title="ACOS % per produs"
            )
            fig_acos.add_hline(y=30, line_dash="dash", line_color="red", annotation_text="Limita 30%")
            st.plotly_chart(fig_acos, use_container_width=True)

            st.subheader("⭐ Grafic Rating per produs")
            fig_rating = px.bar(
                df, x='nume', y='rating',
                color='rating',
                color_continuous_scale=['red', 'yellow', 'green'],
                title="Rating per produs"
            )
            fig_rating.add_hline(y=4.0, line_dash="dash", line_color="orange", annotation_text="Minim recomandat 4.0")
            st.plotly_chart(fig_rating, use_container_width=True)

    elif pagina == "Produse":
        st.title("📦 Produsele tale")
        with st.expander("➕ Adauga produs nou"):
            nume = st.text_input("Nume produs")
            col1, col2 = st.columns(2)
            with col1:
                vanzari = st.number_input("Vanzari lunare (€)", min_value=0)
                cheltuieli = st.number_input("Cheltuieli publicitate (€)", min_value=0)
            with col2:
                rating = st.number_input("Rating", min_value=0.0, max_value=5.0, step=0.1)
            if st.button("💾 Salveaza produs", use_container_width=True):
                if not is_pro and len(produse) >= 2:
                    st.warning("⚠️ Limita 2 produse pe planul gratuit. Upgradeaza la Pro!")
                else:
                    supabase.table("produse").insert({
                        "user_id": st.session_state.user.id,
                        "nume": nume,
                        "vanzari": vanzari,
                        "cheltuieli": cheltuieli,
                        "rating": rating
                    }).execute()
                    st.success("Produs salvat!")
                    st.rerun()

        if len(produse) == 0:
            st.info("Nu ai produse adaugate inca.")
        else:
            st.subheader("Produsele tale")
            for produs in produse:
                col1, col2, col3 = st.columns([3, 1, 1])
                with col1:
                    acos = (produs['cheltuieli'] / produs['vanzari']) * 100
                    st.write(f"📦 **{produs['nume']}** — Rating: {produs['rating']} | ACOS: {acos:.1f}%")
                with col3:
                    if st.button("🗑️ Sterge", key=f"del_{produs['id']}"):
                        supabase.table("produse").delete().eq("id", produs['id']).execute()
                        st.success("Produs sters!")
                        st.rerun()

            st.divider()
            if st.button("🔍 Analizeaza toate produsele", use_container_width=True):
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

    elif pagina == "Reviewuri":
        st.title("💬 Analiza Reviewuri")
        fisier = st.file_uploader("Incarca CSV cu reviewuri", type="csv")
        if fisier is not None:
            df_reviews = pd.read_csv(fisier)
            st.write(f"Reviewuri incarcate: {len(df_reviews)}")
            st.dataframe(df_reviews, use_container_width=True)
            if st.button("🤖 Analizeaza reviewurile negative", use_container_width=True):
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

    elif pagina == "Agent":
        st.title("🤖 Agent AI Amazon")
        st.write("Conversatie cu agentul tau personal Amazon")

        if "messages_agent" not in st.session_state:
            st.session_state.messages_agent = []

        for msg in st.session_state.messages_agent:
            with st.chat_message(msg["role"]):
                st.write(msg["content"])

        if prompt := st.chat_input("Intreaba agentul tau Amazon..."):
            st.session_state.messages_agent.append({"role": "user", "content": prompt})
            with st.chat_message("user"):
                st.write(prompt)

            with st.chat_message("assistant"):
                with st.spinner("Agentul analizeaza..."):
                    model_lc = ChatAnthropic(
                        model="claude-haiku-4-5-20251001",
                        api_key=api_key
                    )

                    context = f"Produsele userului: {produse}" if len(produse) > 0 else ""

                    lc_messages = [
                        SystemMessage(content=f"""Esti un expert Amazon care ajuta sellerii.
                        Raspunzi mereu in romana. Esti direct si dai actiuni concrete.
                        {context}""")
                    ]

                    for msg in st.session_state.messages_agent:
                        if msg["role"] == "user":
                            lc_messages.append(HumanMessage(content=msg["content"]))

                    raspuns = model_lc.invoke(lc_messages)
                    st.write(raspuns.content)
                    st.session_state.messages_agent.append({"role": "assistant", "content": raspuns.content})