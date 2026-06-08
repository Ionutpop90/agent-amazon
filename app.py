import os
import io
import re
import streamlit as st
import anthropic
import pandas as pd
import plotly.express as px
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import tool
from langgraph.prebuilt import create_react_agent
from auth import register_user, login_user, supabase
from payments import create_checkout_session, activate_pro, check_pro
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.units import cm
from datetime import datetime, date

st.set_page_config(page_title="Agent Amazon", page_icon="🛒", layout="wide")

api_key = os.environ.get("ANTHROPIC_API_KEY", "")
client = anthropic.Anthropic(api_key=api_key)

if 'logged_in' not in st.session_state:
    st.session_state.logged_in = False
if 'user' not in st.session_state:
    st.session_state.user = None
if 'pagina' not in st.session_state:
    st.session_state.pagina = "Dashboard"

if not st.session_state.logged_in:
    try:
        session = supabase.auth.get_session()
        if session and session.user:
            st.session_state.logged_in = True
            st.session_state.user = session.user
    except:
        pass

def calculeaza_scor(produs):
    if produs['vanzari'] == 0:
        return 0
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
        if p['vanzari'] == 0:
            continue
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

def salveaza_istoric(user_id, produse):
    today = date.today().isoformat()
    for p in produse:
        if p['vanzari'] == 0:
            continue
        existing = supabase.table("istoric_acos").select("id").eq("user_id", user_id).eq("produs_id", p['id']).eq("data", today).execute()
        if len(existing.data) == 0:
            acos = (p['cheltuieli'] / p['vanzari']) * 100
            supabase.table("istoric_acos").insert({
                "user_id": user_id, "produs_id": p['id'],
                "produs_nume": p['nume'], "acos": acos,
                "rating": p['rating'], "vanzari": p['vanzari'],
                "cheltuieli": p['cheltuieli'], "data": today
            }).execute()

def get_istoric(user_id, produs_id):
    result = supabase.table("istoric_acos").select("*").eq("user_id", user_id).eq("produs_id", produs_id).order("data").execute()
    return result.data

def extrage_asin(link):
    patterns = [
        r'/dp/([A-Z0-9]{10})',
        r'/gp/product/([A-Z0-9]{10})',
        r'asin=([A-Z0-9]{10})',
        r'/product/([A-Z0-9]{10})',
    ]
    for pattern in patterns:
        match = re.search(pattern, link)
        if match:
            return match.group(1)
    return None

def parseaza_vanzari_amazon(valoare):
    try:
        valoare = str(valoare).replace('€', '').replace(',', '.').replace(' ', '').strip()
        return float(valoare)
    except:
        return 0.0

def importa_raport_amazon(df_csv, user_id, cheltuieli_default=0, rating_default=4.0):
    """Importa produsele din raportul CSV Amazon"""
    importate = 0
    erori = []

    col_asin = None
    col_title = None
    col_units = None
    col_sales = None

    for col in df_csv.columns:
        col_lower = col.lower().strip()
        if 'child' in col_lower and 'asin' in col_lower:
            col_asin = col
        elif col_lower == 'title':
            col_title = col
        elif col_lower == 'units ordered' and 'b2b' not in col_lower:
            col_units = col
        elif 'ordered product sales' in col_lower and 'b2b' not in col_lower:
            col_sales = col

    if not col_asin or not col_title:
        return 0, ["Format CSV invalid — nu am gasit coloanele necesare"]

    for _, row in df_csv.iterrows():
        try:
            asin = str(row[col_asin]).strip()
            if len(asin) != 10:
                continue

            title = str(row[col_title]).strip()[:60]
            units = int(row[col_units]) if col_units and str(row[col_units]).strip() not in ['', 'nan'] else 0
            sales_val = parseaza_vanzari_amazon(row[col_sales]) if col_sales else 0.0
            vanzari_int = int(sales_val)

            existing = supabase.table("produse").select("id").eq("user_id", user_id).ilike("nume", f"%{asin}%").execute()

            if len(existing.data) == 0:
                supabase.table("produse").insert({
                    "user_id": user_id,
                    "nume": f"{title[:45]} ({asin})",
                    "vanzari": vanzari_int,
                    "cheltuieli": cheltuieli_default,
                    "rating": rating_default
                }).execute()
                importate += 1
            else:
                supabase.table("produse").update({
                    "vanzari": vanzari_int,
                    "nume": f"{title[:45]} ({asin})"
                }).eq("id", existing.data[0]['id']).execute()
                importate += 1

        except Exception as e:
            erori.append(f"Eroare la {row.get(col_asin, '?')}: {str(e)}")

    return importate, erori

def genereaza_pdf(produse, email):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=2*cm, leftMargin=2*cm, topMargin=2*cm, bottomMargin=2*cm)
    styles = getSampleStyleSheet()
    story = []
    title_style = ParagraphStyle('Title', parent=styles['Title'], fontSize=20, textColor=colors.HexColor('#FF9900'))
    story.append(Paragraph("Agent Amazon — Raport Analiza", title_style))
    story.append(Paragraph(f"Generat pe {datetime.now().strftime('%d/%m/%Y %H:%M')} pentru {email}",
                           ParagraphStyle('Sub', parent=styles['Normal'], fontSize=10, textColor=colors.grey)))
    story.append(Spacer(1, 0.5*cm))
    heading_style = ParagraphStyle('H2', parent=styles['Heading2'], fontSize=14)
    story.append(Paragraph("Sumar Portofoliu", heading_style))
    produse_valide = [p for p in produse if p['vanzari'] > 0]
    if produse_valide:
        acos_list = [(p['cheltuieli'] / p['vanzari']) * 100 for p in produse_valide]
        scor_mediu = sum(calculeaza_scor(p) for p in produse_valide) / len(produse_valide)
        rating_mediu = sum(p['rating'] for p in produse_valide) / len(produse_valide)
        sumar_data = [['Metric', 'Valoare', 'Status'],
            ['Total Produse', str(len(produse)), '✓'],
            ['ACOS Mediu', f"{sum(acos_list)/len(acos_list):.1f}%", 'OK' if sum(acos_list)/len(acos_list) < 30 else 'Atentie'],
            ['Rating Mediu', f"{rating_mediu:.1f}/5.0", 'OK' if rating_mediu >= 4.0 else 'Atentie'],
            ['Scor Sanatate', f"{scor_mediu:.0f}/100", 'OK' if scor_mediu >= 70 else 'Atentie']]
        t = Table(sumar_data, colWidths=[6*cm, 4*cm, 4*cm])
        t.setStyle(TableStyle([('BACKGROUND', (0,0), (-1,0), colors.HexColor('#FF9900')),
            ('TEXTCOLOR', (0,0), (-1,0), colors.white), ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
            ('ALIGN', (0,0), (-1,-1), 'CENTER'), ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, colors.HexColor('#f8f9fa')]),
            ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#dee2e6')), ('FONTSIZE', (0,0), (-1,-1), 10), ('PADDING', (0,0), (-1,-1), 8)]))
        story.append(t)
    story.append(Spacer(1, 0.5*cm))
    story.append(Paragraph("Detalii Produse", heading_style))
    produse_data = [['Produs', 'Vanzari €', 'Cheltuieli €', 'ACOS %', 'Rating', 'Scor']]
    for p in produse_valide:
        acos = (p['cheltuieli'] / p['vanzari']) * 100
        scor = calculeaza_scor(p)
        produse_data.append([p['nume'][:25], f"{p['vanzari']}€", f"{p['cheltuieli']}€", f"{acos:.1f}%", f"{p['rating']}/5.0", f"{scor}/100"])
    t2 = Table(produse_data, colWidths=[5*cm, 2.5*cm, 2.5*cm, 2*cm, 2*cm, 2*cm])
    t2.setStyle(TableStyle([('BACKGROUND', (0,0), (-1,0), colors.HexColor('#FF9900')),
        ('TEXTCOLOR', (0,0), (-1,0), colors.white), ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('ALIGN', (0,0), (-1,-1), 'CENTER'), ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, colors.HexColor('#f8f9fa')]),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#dee2e6')), ('FONTSIZE', (0,0), (-1,-1), 9), ('PADDING', (0,0), (-1,-1), 6)]))
    story.append(t2)
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

@tool
def calculeaza_profit(vanzari: int, acos: float, pret_produs: float, cost_produs: float) -> str:
    """Calculeaza profitul lunar al unui produs Amazon"""
    cheltuieli_ads = vanzari * pret_produs * (acos / 100)
    venit_total = vanzari * pret_produs
    cost_total_produse = vanzari * cost_produs
    profit = venit_total - cheltuieli_ads - cost_total_produse
    marja = (profit / venit_total) * 100 if venit_total > 0 else 0
    return f"Venit: {venit_total:.0f}€ | Ads: {cheltuieli_ads:.0f}€ | Cost produse: {cost_total_produse:.0f}€ | PROFIT: {profit:.0f}€ | Marja: {marja:.1f}% | {'✅ RENTABIL' if profit > 0 else '❌ PIERDERE'}"

@tool
def calculeaza_acos_optim(marja_dorita: float, cost_produs: float, pret_vanzare: float) -> str:
    """Calculeaza ACOS-ul maxim pentru marja dorita"""
    marja_bruta = ((pret_vanzare - cost_produs) / pret_vanzare) * 100
    acos_maxim = marja_bruta - marja_dorita
    return f"Marja bruta: {marja_bruta:.1f}% | ACOS maxim recomandat: {acos_maxim:.1f}%"

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
    produse_valide = [p for p in produse if p['vanzari'] > 0]
    alerte = sum(1 for p in produse_valide if p['rating'] < 4.0 or (p['cheltuieli']/p['vanzari'])*100 >= 30)
    produse_cu_probleme = sum(1 for p in produse_valide if calculeaza_scor(p) < 75)

    if len(produse_valide) > 0:
        salveaza_istoric(st.session_state.user.id, produse_valide)

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
        if st.button("👤  Profil", use_container_width=True):
            st.session_state.pagina = "Profil"
        st.divider()
        if is_pro:
            st.success("⭐ Plan Pro Activ")
        else:
            st.info("🆓 Plan Gratuit\n2 produse maxim")
            if st.button("⭐ Upgrade Pro — 29€/lună", use_container_width=True):
                success, url = create_checkout_session(
                    st.session_state.user.email, st.session_state.user.id,
                    success_url="https://amazonanalyzer.org?success=true",
                    cancel_url="https://amazonanalyzer.org?cancel=true"
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

    if pagina == "Dashboard":
        st.title("📊 Dashboard")
        if len(produse_valide) == 0:
            show_onboarding()
        else:
            acos_list = [(p['cheltuieli'] / p['vanzari']) * 100 for p in produse_valide]
            rating_mediu = sum(p['rating'] for p in produse_valide) / len(produse_valide)
            scor_mediu = sum(calculeaza_scor(p) for p in produse_valide) / len(produse_valide)
            acos_mediu = sum(acos_list) / len(acos_list)
            benchmark = benchmark_industrie()

            col1, col2, col3, col4 = st.columns(4)
            with col1: st.metric("Total Produse", len(produse))
            with col2: st.metric("ACOS Mediu", f"{acos_mediu:.1f}%")
            with col3: st.metric("Rating Mediu", f"{rating_mediu:.1f} ⭐")
            with col4:
                emoji_scor, _ = culoare_scor(scor_mediu)
                st.metric("Scor Sanatate", f"{scor_mediu:.0f}/100 {emoji_scor}")

            if alerte > 0:
                st.warning(f"⚠️ Ai {alerte} produse care necesita atentie!")

            st.divider()
            st.subheader("📈 Comparatie cu Media Industriei")
            col1, col2, col3 = st.columns(3)
            with col1:
                diff_acos = acos_mediu - benchmark['acos_mediu']
                st.metric("ACOS tau vs Industrie", f"{acos_mediu:.1f}%",
                         delta=f"{diff_acos:+.1f}% fata de {benchmark['acos_mediu']}%", delta_color="inverse")
            with col2:
                diff_rating = rating_mediu - benchmark['rating_mediu']
                st.metric("Rating tau vs Industrie", f"{rating_mediu:.1f}",
                         delta=f"{diff_rating:+.1f} fata de {benchmark['rating_mediu']}", delta_color="normal")
            with col3:
                diff_scor = scor_mediu - benchmark['scor_mediu']
                st.metric("Scor tau vs Industrie", f"{scor_mediu:.0f}/100",
                         delta=f"{diff_scor:+.0f} fata de {benchmark['scor_mediu']:.0f}", delta_color="normal")

            st.divider()
            st.subheader("📉 Istoric ACOS per produs")
            for produs in produse_valide:
                istoric = get_istoric(st.session_state.user.id, produs['id'])
                if len(istoric) > 1:
                    df_istoric = pd.DataFrame(istoric)
                    fig = px.line(df_istoric, x='data', y='acos',
                                 title=f"Evolutie ACOS — {produs['nume']}", markers=True)
                    fig.add_hline(y=30, line_dash="dash", line_color="red", annotation_text="Limita 30%")
                    st.plotly_chart(fig, use_container_width=True)
                else:
                    st.info(f"📦 {produs['nume']} — Istoric disponibil dupa mai multe zile de date.")

            st.divider()
            col1, col2 = st.columns([4, 1])
            with col2:
                if st.button("📄 Export PDF", use_container_width=True):
                    with st.spinner("Generez raportul..."):
                        pdf_buffer = genereaza_pdf(produse_valide, st.session_state.user.email)
                        st.download_button(label="⬇️ Descarca PDF", data=pdf_buffer,
                            file_name=f"raport_amazon_{datetime.now().strftime('%Y%m%d')}.pdf",
                            mime="application/pdf", use_container_width=True)

            recomandari = genereaza_recomandari(produse_valide)
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

            st.divider()
            st.subheader("💊 Scor Sanatate Produse")
            for produs in produse_valide:
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

            st.divider()
            df = pd.DataFrame(produse_valide)
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

    elif pagina == "Produse":
        st.title("📦 Produsele tale")
        tab1, tab2, tab3 = st.tabs(["➕ Adauga Manual", "🔗 Adauga din Link", "📊 Import Raport Amazon"])

        with tab1:
            with st.expander("➕ Adauga produs manual", expanded=True):
                nume = st.text_input("Nume produs", key="manual_nume")
                col1, col2 = st.columns(2)
                with col1:
                    vanzari = st.number_input("Vanzari lunare (€)", min_value=0, key="manual_vanzari")
                    cheltuieli = st.number_input("Cheltuieli publicitate (€)", min_value=0, key="manual_cheltuieli")
                with col2:
                    rating = st.number_input("Rating", min_value=0.0, max_value=5.0, step=0.1, key="manual_rating")
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

        with tab2:
            st.markdown("### 🔗 Adauga produs din link Amazon")
            st.info("Pune link-ul produsului tau de pe Amazon!")
            link_amazon = st.text_input("Link Amazon", placeholder="https://www.amazon.es/dp/B08XYZ123...")
            if link_amazon:
                asin = extrage_asin(link_amazon)
                if asin:
                    st.success(f"✅ ASIN detectat: **{asin}**")
                    col1, col2 = st.columns(2)
                    with col1:
                        nume_link = st.text_input("Nume produs", key="link_nume")
                        vanzari_link = st.number_input("Vanzari lunare (€)", min_value=0, key="link_vanzari")
                        cheltuieli_link = st.number_input("Cheltuieli publicitate (€)", min_value=0, key="link_cheltuieli")
                    with col2:
                        rating_link = st.number_input("Rating", min_value=0.0, max_value=5.0, step=0.1, key="link_rating")
                        st.text_input("ASIN", value=asin, disabled=True)
                        marketplace = st.selectbox("Marketplace", ["amazon.es", "amazon.de", "amazon.fr", "amazon.it", "amazon.co.uk", "amazon.com"])
                    if st.button("💾 Salveaza produs din link", use_container_width=True, type="primary"):
                        if not is_pro and len(produse) >= 2:
                            st.warning("⚠️ Limita 2 produse pe planul gratuit. Upgradeaza la Pro!")
                        elif not nume_link:
                            st.warning("⚠️ Introdu numele produsului!")
                        else:
                            supabase.table("produse").insert({
                                "user_id": st.session_state.user.id,
                                "nume": f"{nume_link} ({asin})",
                                "vanzari": vanzari_link,
                                "cheltuieli": cheltuieli_link,
                                "rating": rating_link
                            }).execute()
                            st.success(f"✅ Produs {asin} salvat!")
                            st.rerun()
                else:
                    st.error("❌ Nu am putut extrage ASIN-ul!")

        with tab3:
            st.markdown("### 📊 Import Raport Amazon Seller Central")
            st.info("""**Cum descarci raportul:**
1. Mergi in Amazon Seller Central → Reports → Business Reports
2. Click pe **"Detail page sales and traffic by child item"**
3. Seteaza perioada dorita (ex: ultima luna)
4. Click **"Download (.csv)"**
5. Incarca fișierul mai jos""")

            csv_file = st.file_uploader("Incarca raportul CSV Amazon", type="csv", key="amazon_csv")

            if csv_file is not None:
                try:
                    df_amazon = pd.read_csv(csv_file, sep=',')
                    
                    st.success(f"✅ Fisier incarcat: {len(df_amazon)} produse detectate")
                    st.dataframe(df_amazon[['(Child) ASIN', 'Title', 'Units ordered', 'Ordered Product Sales']].head(5) if '(Child) ASIN' in df_amazon.columns else df_amazon.head(5))

                    st.divider()
                    st.markdown("**Seteaza valorile implicite pentru cheltuieli:**")
                    col1, col2 = st.columns(2)
                    with col1:
                        cheltuieli_default = st.number_input("Cheltuieli publicitate implicite (€)", min_value=0, value=0, key="import_cheltuieli")
                    with col2:
                        rating_default = st.number_input("Rating implicit", min_value=0.0, max_value=5.0, value=4.0, step=0.1, key="import_rating")

                    st.info("💡 Poti actualiza cheltuielile si rating-ul pentru fiecare produs dupa import!")

                    if st.button("🚀 Importa toate produsele", use_container_width=True, type="primary"):
                        if not is_pro and len(produse) >= 2:
                            st.warning("⚠️ Limita 2 produse pe planul gratuit. Upgradeaza la Pro!")
                        else:
                            with st.spinner("Se importa produsele..."):
                                importate, erori = importa_raport_amazon(df_amazon, st.session_state.user.id, cheltuieli_default, rating_default)
                                st.success(f"✅ {importate} produse importate/actualizate!")
                                if erori:
                                    st.warning(f"⚠️ {len(erori)} erori: {', '.join(erori[:3])}")
                                st.rerun()

                except Exception as e:
                    st.error(f"❌ Eroare la citirea fisierului: {str(e)}")

        if len(produse) > 0:
            st.divider()
            st.subheader("Produsele tale")
            for produs in produse:
                scor = calculeaza_scor(produs)
                emoji, _ = culoare_scor(scor)
                acos = (produs['cheltuieli'] / produs['vanzari']) * 100 if produs['vanzari'] > 0 else 0
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
                    if produs['vanzari'] == 0:
                        continue
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

    elif pagina == "Agent":
        st.title("🤖 Agent AI Amazon")
        st.info("💡 Intreaba agentul: 'Calculeaza profitul pentru 500 vanzari, ACOS 30%, pret 15€, cost 5€'")
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
                    tools = [calculeaza_profit, calculeaza_acos_optim]
                    scoruri = {p['nume']: calculeaza_scor(p) for p in produse_valide}
                    lc_messages = [SystemMessage(content=f"""Esti un expert Amazon care ajuta sellerii romani.
                        Raspunzi MEREU in romana. Esti direct si dai actiuni concrete.
                        Produsele userului: {produse_valide}
                        Scoruri sanatate: {scoruri}
                        Benchmark industrie: {benchmark_industrie()}
                        Foloseste tool-urile pentru calcule financiare.""")]
                    for msg in st.session_state.messages_agent:
                        if msg["role"] == "user":
                            lc_messages.append(HumanMessage(content=msg["content"]))
                    try:
                        agent = create_react_agent(model=model_lc, tools=tools)
                        rezultat = agent.invoke({"messages": lc_messages})
                        raspuns_text = rezultat["messages"][-1].content
                    except Exception:
                        raspuns = model_lc.invoke(lc_messages)
                        raspuns_text = raspuns.content
                    st.write(raspuns_text)
                    st.session_state.messages_agent.append({"role": "assistant", "content": raspuns_text})

    elif pagina == "Profil":
        st.title("👤 Profilul Meu")
        col1, col2 = st.columns([1, 2])
        with col1:
            st.markdown(f"""
            <div style="background:#f8f9fa; padding:2rem; border-radius:12px; text-align:center;">
                <div style="font-size:4rem;">👤</div>
                <h3>{st.session_state.user.email}</h3>
                <p style="color:#888;">Membru din {datetime.now().strftime('%B %Y')}</p>
            </div>
            """, unsafe_allow_html=True)
        with col2:
            st.subheader("Informatii Cont")
            st.write(f"**Email:** {st.session_state.user.email}")
            st.write(f"**Plan:** {'⭐ Pro' if is_pro else '🆓 Gratuit'}")
            st.write(f"**Produse active:** {len(produse)}")
            st.write(f"**ID Cont:** `{str(st.session_state.user.id)[:8]}...`")
            st.divider()
            st.subheader("Statistici")
            if len(produse_valide) > 0:
                acos_list = [(p['cheltuieli'] / p['vanzari']) * 100 for p in produse_valide]
                scor_mediu = sum(calculeaza_scor(p) for p in produse_valide) / len(produse_valide)
                col1, col2, col3 = st.columns(3)
                with col1: st.metric("Produse", len(produse))
                with col2: st.metric("ACOS Mediu", f"{sum(acos_list)/len(acos_list):.1f}%")
                with col3:
                    emoji, _ = culoare_scor(scor_mediu)
                    st.metric("Scor Mediu", f"{scor_mediu:.0f} {emoji}")
            else:
                st.info("Adauga produse pentru a vedea statisticile.")
            st.divider()
            if not is_pro:
                st.subheader("🚀 Upgrade la Pro")
                st.write("Deblocheaza toate functiile.")
                if st.button("⭐ Upgrade la Pro — 29€/lună", use_container_width=True, type="primary"):
                    success, url = create_checkout_session(
                        st.session_state.user.email, st.session_state.user.id,
                        success_url="https://amazonanalyzer.org?success=true",
                        cancel_url="https://amazonanalyzer.org?cancel=true"
                    )
                    if success:
                        st.markdown(f"[👉 Plateste aici]({url})")
            else:
                st.success("⭐ Esti pe Plan Pro — ai acces la toate functiile!")