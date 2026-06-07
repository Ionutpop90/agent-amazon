import os
import io
import streamlit as st
import anthropic
import pandas as pd
import plotly.express as px
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage
from auth import register_user, login_user, supabase
from payments import create_checkout_session, activate_pro, check_pro
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.units import cm
from datetime import datetime

st.set_page_config(page_title="Agent Amazon", page_icon="🛒", layout="wide")

api_key = os.environ.get("ANTHROPIC_API_KEY", "")
client = anthropic.Anthropic(api_key=api_key)

if 'logged_in' not in st.session_state:
    st.session_state.logged_in = False
if 'user' not in st.session_state:
    st.session_state.user = None
if 'pagina' not in st.session_state:
    st.session_state.pagina = "Dashboard"

def calculeaza_scor(produs):
    scor = 100
    acos = (produs['cheltuieli'] / produs['vanzari']) * 100
    if produs['rating'] < 3.5: scor -= 40
    elif produs['rating'] < 4.0: scor -= 20
    elif produs['rating'] < 4.3: scor -= 10
    if acos > 40: scor -= 30
    elif acos > 30: scor -= 15
    elif acos > 20: scor -= 5
    return max(0, scor)

def culoare_scor(scor):
    if scor >= 75: return "🟢", "success"
    elif scor >= 50: return "🟡", "warning"
    else: return "🔴", "error"

def benchmark_industrie():
    return {"acos_mediu": 25.0, "rating_mediu": 4.2, "scor_mediu": 78.0}

def genereaza_recomandari(produse):
    recomandari = []
    for p in produse:
        acos = (p['cheltuieli'] / p['vanzari']) * 100
        scor = calculeaza_scor(p)
        if p['rating'] < 4.0:
            recomandari.append({"prioritate": "URGENT", "emoji": "🔴",
                "actiune": f"Analizeaza reviewurile negative pentru {p['nume']}",
                "motiv": f"Rating {p['rating']} sub limita recomandata de 4.0"})
        if acos > 30:
            recomandari.append({"prioritate": "IMPORTANT", "emoji": "🟡",
                "actiune": f"Reduce ACOS-ul pentru {p['nume']}",
                "motiv": f"ACOS {acos:.1f}% peste limita de 30%"})
        if scor < 50:
            recomandari.append({"prioritate": "URGENT", "emoji": "🔴",
                "actiune": f"Optimizeaza urgent {p['nume']}",
                "motiv": f"Scor sanatate {scor}/100 produs in pericol"})
    return recomandari[:3]

def genereaza_pdf(produse, email):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4,
                           rightMargin=2*cm, leftMargin=2*cm,
                           topMargin=2*cm, bottomMargin=2*cm)
    styles = getSampleStyleSheet()
    story = []

    title_style = ParagraphStyle('Title', parent=styles['Title'],
                                fontSize=20, textColor=colors.HexColor('#FF9900'))
    story.append(Paragraph("Agent Amazon — Raport Analiza", title_style))
    story.append(Paragraph(f"Generat pe {datetime.now().strftime('%d/%m/%Y %H:%M')} pentru {email}",
                           ParagraphStyle('Sub', parent=styles['Normal'], fontSize=10, textColor=colors.grey)))
    story.append(Spacer(1, 0.5*cm))

    heading_style = ParagraphStyle('H2', parent=styles['Heading2'], fontSize=14)
    story.append(Paragraph("Sumar Portofoliu", heading_style))

    acos_list = [(p['cheltuieli'] / p['vanzari']) * 100 for p in produse]
    scor_mediu = sum(calculeaza_scor(p) for p in produse) / len(produse)
    rating_mediu = sum(p['rating'] for p in produse) / len(produse)

    sumar_data = [
        ['Metric', 'Valoare', 'Status'],
        ['Total Produse', str(len(produse)), '✓'],
        ['ACOS Mediu', f"{sum(acos_list)/len(acos_list):.1f}%", 'OK' if sum(acos_list)/len(acos_list) < 30 else 'Atentie'],
        ['Rating Mediu', f"{rating_mediu:.1f}/5.0", 'OK' if rating_mediu >= 4.0 else 'Atentie'],
        ['Scor Sanatate', f"{scor_mediu:.0f}/100", 'OK' if scor_mediu >= 70 else 'Atentie'],
    ]
    t = Table(sumar_data, colWidths=[6*cm, 4*cm, 4*cm])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#FF9900')),
        ('TEXTCOLOR', (0,0), (-1,0), colors.white),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, colors.HexColor('#f8f9fa')]),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#dee2e6')),
        ('FONTSIZE', (0,0), (-1,-1), 10),
        ('PADDING', (0,0), (-1,-1), 8),
    ]))
    story.append(t)
    story.append(Spacer(1, 0.5*cm))

    story.append(Paragraph("Detalii Produse", heading_style))
    produse_data = [['Produs', 'Vanzari €', 'Cheltuieli €', 'ACOS %', 'Rating', 'Scor']]
    for p in produse:
        acos = (p['cheltuieli'] / p['vanzari']) * 100
        scor = calculeaza_scor(p)
        produse_data.append([p['nume'][:25], f"{p['vanzari']}€", f"{p['cheltuieli']}€",
                             f"{acos:.1f}%", f"{p['rating']}/5.0", f"{scor}/100"])
    t2 = Table(produse_data, colWidths=[5*cm, 2.5*cm, 2.5*cm, 2*cm, 2*cm, 2*cm])
    t2.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#FF9900')),
        ('TEXTCOLOR', (0,0), (-1,0), colors.white),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, colors.HexColor('#f8f9fa')]),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#dee2e6')),
        ('FONTSIZE', (0,0), (-1,-1), 9),
        ('PADDING', (0,0), (-1,-1), 6),
    ]))
    story.append(t2)
    story.append(Spacer(1, 0.3*cm))

    recomandari = genereaza_recomandari(produse)
    if recomandari:
        story.append(Paragraph("Recomandari Prioritare", heading_style))
        rec_data = [['Prioritate', 'Actiune', 'Motiv']]
        for rec in recomandari:
            rec_data.append([rec['prioritate'], rec['actiune'][:40], rec['motiv'][:40]])
        t3 = Table(rec_data, colWidths=[3*cm, 7*cm, 6*cm])
        t3.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#FF9900')),
            ('TEXTCOLOR', (0,0), (-1,0), colors.white),
            ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
            ('ALIGN', (0,0), (-1,-1), 'LEFT'),
            ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, colors.HexColor('#f8f9fa')]),
            ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#dee2e6')),
            ('FONTSIZE', (0,0), (-1,-1), 9),
            ('PADDING', (0,0), (-1,-1), 6),
        ]))
        story.append(t3)

    story.append(Spacer(1, 0.5*cm))
    story.append(Paragraph("Generat de Agent Amazon — Powered by Claude AI | amazonanalyzer.org",
                           ParagraphStyle('Footer', parent=styles['Normal'], fontSize=8, textColor=colors.grey)))
    doc.build(story)
    buffer.seek(0)
    return buffer

def show_onboarding():
    st.markdown("## 👋 Bun venit la Agent Amazon!")
    st.markdown("Hai sa configurezi contul tau in **3 pasi simpli**:")
    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown("### ✅ Pasul 1\n**Adauga primul produs**\n\nIntrodu ACOS, rating si vanzarile tale.")
        if st.button("➕ Adauga primul produs", use_container_width=True, type="primary"):
            st.session_state.pagina = "Produse"
            st.rerun()
    with col2:
        st.markdown("### 📊 Pasul 2\n**Analizeaza cu AI**\n\nVezi Scorul de Sanatate si TOP 3 actiuni.")
    with col3:
        st.markdown("### 🤖 Pasul 3\n**Vorbeste cu Agentul AI**\n\nAgentul iti cunoaste produsele si da recomandari.")
        if st.button("🤖 Deschide Agent AI", use_container_width=True):
            st.session_state.pagina = "Agent"
            st.rerun()
    st.divider()
    col1, col2, col3 = st.columns(3)
    with col1: st.info("📊 **Dashboard complet**\nACOS, Rating, Scor Sanatate")
    with col2: st.info("🤖 **Agent AI personal**\nConversatie directa cu Claude")
    with col3: st.info("💬 **Analiza reviewuri**\nIdentifica problemele rapid")

# AUTH
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
    result = supabase.table("produse").select("*").eq("user_id", st.session_state.user.id).execute()
    produse = result.data
    is_pro = check_pro(st.session_state.user.id)
    alerte = sum(1 for p in produse if p['rating'] < 4.0 or (p['cheltuieli']/p['vanzari'])*100 >= 30)
    produse_cu_probleme = sum(1 for p in produse if calculeaza_scor(p) < 75)

    # SIDEBAR
    with st.sidebar:
        st.title("🛒 Agent Amazon")
        st.write(f"👤 {st.session_state.user.email}")
        if alerte > 0:
            st.error(f"⚠️ {alerte} alerte active!")
        st.divider()
        st.markdown("### Navigare")
        if st.button(f"📊  Dashboard {'🔴' if alerte > 0 else ''}", use_container_width=True):
            st.session_state.pagina = "Dashboard"
        if st.button(f"📦  Produse {'⚠️' if produse_cu_probleme > 0 else ''}", use_container_width=True):
            st.session_state.pagina = "Produse"
        if st.button("💬  Reviewuri", use_container_width=True):
            st.session_state.pagina = "Reviewuri"
        if st.button("🤖  Agent AI", use_container_width=True):
            st.session_state.pagina = "Agent"
        st.divider()
        if is_pro:
            st.success("⭐ Plan Pro Activ")
        else:
            st.info("🆓 Plan Gratuit\n2 produse maxim")
            if st.button("⭐ Upgrade Pro — 29€/lună", use_container_width=True):
                success, url = create_checkout_session(
                    st.session_state.user.email, st.session_state.user.id,
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

    pagina = st.session_state.pagina

    # DASHBOARD
    if pagina == "Dashboard":
        st.title("📊 Dashboard")
        if len(produse) == 0:
            show_onboarding()
        else:
            acos_list = [(p['cheltuieli'] / p['vanzari']) * 100 for p in produse]
            rating_mediu = sum(p['rating'] for p in produse) / len(produse)
            scor_mediu = sum(calculeaza_scor(p) for p in produse) / len(produse)
            acos_mediu = sum(acos_list) / len(acos_list)
            benchmark = benchmark_industrie()

            # Metrici
            col1, col2, col3, col4 = st.columns(4)
            with col1: st.metric("Total Produse", len(produse))
            with col2: st.metric("ACOS Mediu", f"{acos_mediu:.1f}%")
            with col3: st.metric("Rating Mediu", f"{rating_mediu:.1f} ⭐")
            with col4:
                emoji_scor, _ = culoare_scor(scor_mediu)
                st.metric("Scor Sanatate", f"{scor_mediu:.0f}/100 {emoji_scor}")

            if alerte > 0:
                st.warning(f"⚠️ Ai {alerte} produse care necesita atentie!")

            # Benchmark
            st.divider()
            st.subheader("📈 Comparatie cu Media Industriei")
            col1, col2, col3 = st.columns(3)
            with col1:
                diff_acos = acos_mediu - benchmark['acos_mediu']
                st.metric("ACOS tau vs Industrie", f"{acos_mediu:.1f}%",
                         delta=f"{diff_acos:+.1f}% fata de {benchmark['acos_mediu']}%",
                         delta_color="inverse")
            with col2:
                diff_rating = rating_mediu - benchmark['rating_mediu']
                st.metric("Rating tau vs Industrie", f"{rating_mediu:.1f}",
                         delta=f"{diff_rating:+.1f} fata de {benchmark['rating_mediu']}",
                         delta_color="normal")
            with col3:
                diff_scor = scor_mediu - benchmark['scor_mediu']
                st.metric("Scor tau vs Industrie", f"{scor_mediu:.0f}/100",
                         delta=f"{diff_scor:+.0f} fata de {benchmark['scor_mediu']:.0f}",
                         delta_color="normal")

            # Export PDF
            st.divider()
            col1, col2 = st.columns([4, 1])
            with col2:
                if st.button("📄 Export PDF", use_container_width=True):
                    with st.spinner("Generez raportul..."):
                        pdf_buffer = genereaza_pdf(produse, st.session_state.user.email)
                        st.download_button(
                            label="⬇️ Descarca PDF",
                            data=pdf_buffer,
                            file_name=f"raport_amazon_{datetime.now().strftime('%Y%m%d')}.pdf",
                            mime="application/pdf",
                            use_container_width=True
                        )

            # TOP 3
            recomandari = genereaza_recomandari(produse)
            if recomandari:
                st.subheader("🎯 TOP 3 Actiuni pentru AZI")
                for i, rec in enumerate(recomandari):
                    with st.expander(f"{rec['emoji']} {rec['prioritate']} — {rec['actiune']}"):
                        st.write(f"**Motiv:** {rec['motiv']}")
                        if st.button("🤖 Obtine plan detaliat", key=f"rec_{i}"):
                            with st.spinner("Claude genereaza plan..."):
                                mesaj = client.messages.create(
                                    model="claude-haiku-4-5-20251001", max_tokens=200,
                                    messages=[{"role": "user", "content": f"Plan de actiune in 3 pasi pentru: {rec['actiune']}. Motiv: {rec['motiv']}"}]
                                )
                                st.write(mesaj.content[0].text)

            # Scor sanatate
            st.divider()
            st.subheader("💊 Scor Sanatate Produse")
            for produs in produse:
                scor = calculeaza_scor(produs)
                emoji, _ = culoare_scor(scor)
                acos = (produs['cheltuieli'] / produs['vanzari']) * 100
                col1, col2, col3, col4 = st.columns([3, 1, 1, 1])
                with col1:
                    st.write(f"**{produs['nume']}**")
                    st.progress(scor / 100)
                with col2: st.metric("Scor", f"{scor} {emoji}")
                with col3: st.metric("Rating", produs['rating'])
                with col4: st.metric("ACOS", f"{acos:.1f}%")

            # Grafice
            st.divider()
            df = pd.DataFrame(produse)
            df['ACOS %'] = df.apply(lambda r: (r['cheltuieli']/r['vanzari'])*100, axis=1)
            df['Scor'] = df.apply(lambda r: calculeaza_scor(r), axis=1)
            col1, col2 = st.columns(2)
            with col1:
                fig = px.bar(df, x='nume', y='ACOS %', color='ACOS %',
                            color_continuous_scale=['green', 'yellow', 'red'], title="ACOS % per produs")
                fig.add_hline(y=30, line_dash="dash", line_color="red", annotation_text="Limita 30%")
                st.plotly_chart(fig, use_container_width=True)
            with col2:
                fig2 = px.bar(df, x='nume', y='Scor', color='Scor',
                             color_continuous_scale=['red', 'yellow', 'green'], title="Scor Sanatate")
                fig2.add_hline(y=70, line_dash="dash", line_color="orange", annotation_text="Minim recomandat")
                st.plotly_chart(fig2, use_container_width=True)

    # PRODUSE
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
                        "nume": nume, "vanzari": vanzari,
                        "cheltuieli": cheltuieli, "rating": rating
                    }).execute()
                    st.success("Produs salvat!")
                    st.rerun()

        if len(produse) == 0:
            st.info("Nu ai produse adaugate inca.")
        else:
            for produs in produse:
                scor = calculeaza_scor(produs)
                emoji, _ = culoare_scor(scor)
                acos = (produs['cheltuieli'] / produs['vanzari']) * 100
                col1, col2 = st.columns([5, 1])
                with col1:
                    st.write(f"{emoji} **{produs['nume']}** — Rating: {produs['rating']} | ACOS: {acos:.1f}% | Scor: {scor}/100")
                with col2:
                    if st.button("🗑️ Sterge", key=f"del_{produs['id']}"):
                        supabase.table("produse").delete().eq("id", produs['id']).execute()
                        st.success("Produs sters!")
                        st.rerun()

            st.divider()
            if st.button("🔍 Analizeaza toate produsele", use_container_width=True):
                for produs in produse:
                    scor = calculeaza_scor(produs)
                    emoji, _ = culoare_scor(scor)
                    acos = (produs['cheltuieli'] / produs['vanzari']) * 100
                    with st.expander(f"{emoji} {produs['nume']} — Scor {scor}/100 | ACOS {acos:.1f}%"):
                        if produs['rating'] < 4.0:
                            st.warning(f"⚠️ Rating slab: {produs['rating']}")
                            with st.spinner("Claude analizeaza..."):
                                mesaj = client.messages.create(
                                    model="claude-haiku-4-5-20251001", max_tokens=150,
                                    messages=[{"role": "user", "content": f"2 actiuni concrete pentru '{produs['nume']}' cu rating {produs['rating']}: "}]
                                )
                                st.write(mesaj.content[0].text)
                        else:
                            st.success(f"✅ Rating bun: {produs['rating']}")

    # REVIEWURI
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
                                model="claude-haiku-4-5-20251001", max_tokens=150,
                                messages=[{"role": "user", "content": f"Solutie concreta in 2 randuri pentru acest review negativ: '{row['review']}'"}]
                            )
                            st.write(mesaj.content[0].text)

    # AGENT AI
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
                    model_lc = ChatAnthropic(model="claude-haiku-4-5-20251001", api_key=api_key)
                    scoruri = {p['nume']: calculeaza_scor(p) for p in produse}
                    lc_messages = [SystemMessage(content=f"""Esti un expert Amazon care ajuta sellerii.
                        Raspunzi mereu in romana. Esti direct si dai actiuni concrete.
                        Produsele userului: {produse}
                        Scoruri sanatate: {scoruri}
                        Benchmark industrie: {benchmark_industrie()}""")]
                    for msg in st.session_state.messages_agent:
                        if msg["role"] == "user":
                            lc_messages.append(HumanMessage(content=msg["content"]))
                    raspuns = model_lc.invoke(lc_messages)
                    st.write(raspuns.content)
                    st.session_state.messages_agent.append({"role": "assistant", "content": raspuns.content})