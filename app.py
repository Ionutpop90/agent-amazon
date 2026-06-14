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
st.markdown("""
<style>
    div[data-testid="metric-container"] {
        background: white;
        border-radius: 8px;
        padding: 1rem;
        border-left: 4px solid #FF9900;
        box-shadow: 0 1px 4px rgba(0,0,0,0.08);
    }
    .stProgress > div > div {
        background: #FF9900;
    }
</style>
""", unsafe_allow_html=True)

api_key = os.environ.get("ANTHROPIC_API_KEY", "")
client = anthropic.Anthropic(api_key=api_key)

if 'logged_in' not in st.session_state:
    st.session_state.logged_in = False
if 'user' not in st.session_state:
    st.session_state.user = None
if 'page' not in st.session_state:
    st.session_state.page = "Dashboard"

if not st.session_state.logged_in:
    try:
        session = supabase.auth.get_session()
        if session and session.user:
            st.session_state.logged_in = True
            st.session_state.user = session.user
    except:
        pass
    try:
        params = st.query_params
        if 'login' in params and params['login'] == 'google':
            session = supabase.auth.get_session()
            if session and session.user:
                st.session_state.logged_in = True
                st.session_state.user = session.user
                st.rerun()
    except:
        pass

def calculate_score(product):
    if product['vanzari'] == 0:
        return 0
    score = 100
    acos = (product['cheltuieli'] / product['vanzari']) * 100
    if product['rating'] < 3.5: score -= 40
    elif product['rating'] < 4.0: score -= 20
    elif product['rating'] < 4.3: score -= 10
    if acos > 40: score -= 30
    elif acos > 30: score -= 15
    elif acos > 20: score -= 5
    return max(0, score)

def score_color(score):
    if score >= 75: return "🟢", "success"
    elif score >= 50: return "🟡", "warning"
    else: return "🔴", "error"

def industry_benchmark():
    return {"acos_avg": 25.0, "rating_avg": 4.2, "score_avg": 78.0}

def generate_recommendations(products):
    recommendations = []
    for p in products:
        if p['vanzari'] == 0:
            continue
        acos = (p['cheltuieli'] / p['vanzari']) * 100
        score = calculate_score(p)
        if p['rating'] < 4.0:
            recommendations.append({"priority": "URGENT", "emoji": "🔴",
                "action": f"Analyze negative reviews for {p['nume']}",
                "reason": f"Rating {p['rating']} below recommended minimum of 4.0"})
        if acos > 30:
            recommendations.append({"priority": "IMPORTANT", "emoji": "🟡",
                "action": f"Reduce ACOS for {p['nume']}",
                "reason": f"ACOS {acos:.1f}% above 30% limit"})
        if score < 50:
            recommendations.append({"priority": "URGENT", "emoji": "🔴",
                "action": f"Urgently optimize {p['nume']}",
                "reason": f"Health score {score}/100 — product at risk"})
    return recommendations[:3]

def save_history(user_id, products):
    today = date.today().isoformat()
    for p in products:
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

def get_history(user_id, product_id):
    result = supabase.table("istoric_acos").select("*").eq("user_id", user_id).eq("produs_id", product_id).order("data").execute()
    return result.data

def extract_asin(link):
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

def clean_value(val):
    try:
        return float(str(val).replace('€', '').replace(',', '').replace(' ', '').strip())
    except:
        return 0.0

def import_amazon_report(df_csv, user_id, default_spend=0, default_rating=4.0):
    imported = 0
    errors = []
    col_asin = None
    col_title = None
    col_sales = None
    for col in df_csv.columns:
        col_lower = col.lower().strip()
        if 'child' in col_lower and 'asin' in col_lower:
            col_asin = col
        elif col_lower == 'title':
            col_title = col
        elif 'ordered product sales' in col_lower and 'b2b' not in col_lower:
            col_sales = col
    if not col_asin or not col_title:
        return 0, ["Invalid CSV format"]
    for _, row in df_csv.iterrows():
        try:
            asin = str(row[col_asin]).strip()
            if len(asin) != 10:
                continue
            if str(row[col_asin]).strip() == str(row.get('(Parent) ASIN', '')).strip():
                continue
            title = str(row[col_title]).strip()[:60]
            if not title or title == 'nan':
                continue
            sales_val = clean_value(row[col_sales]) if col_sales else 0.0
            existing = supabase.table("produse").select("id").eq("user_id", user_id).ilike("nume", f"%{asin}%").execute()
            if len(existing.data) == 0:
                supabase.table("produse").insert({
                    "user_id": user_id,
                    "nume": f"{title[:45]} ({asin})",
                    "vanzari": int(sales_val),
                    "cheltuieli": default_spend,
                    "rating": default_rating
                }).execute()
                imported += 1
            else:
                supabase.table("produse").update({
                    "vanzari": int(sales_val),
                    "nume": f"{title[:45]} ({asin})"
                }).eq("id", existing.data[0]['id']).execute()
                imported += 1
        except Exception as e:
            errors.append(f"Error: {str(e)}")
    return imported, errors

def generate_pdf(products, email):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=2*cm, leftMargin=2*cm, topMargin=2*cm, bottomMargin=2*cm)
    styles = getSampleStyleSheet()
    story = []
    title_style = ParagraphStyle('Title', parent=styles['Title'], fontSize=20, textColor=colors.HexColor('#FF9900'))
    story.append(Paragraph("Agent Amazon — Analysis Report", title_style))
    story.append(Paragraph(f"Generated on {datetime.now().strftime('%d/%m/%Y %H:%M')} for {email}",
                           ParagraphStyle('Sub', parent=styles['Normal'], fontSize=10, textColor=colors.grey)))
    story.append(Spacer(1, 0.5*cm))
    heading_style = ParagraphStyle('H2', parent=styles['Heading2'], fontSize=14)
    story.append(Paragraph("Portfolio Summary", heading_style))
    valid_products = [p for p in products if p['vanzari'] > 0]
    if valid_products:
        acos_list = [(p['cheltuieli'] / p['vanzari']) * 100 for p in valid_products]
        avg_score = sum(calculate_score(p) for p in valid_products) / len(valid_products)
        avg_rating = sum(p['rating'] for p in valid_products) / len(valid_products)
        summary_data = [['Metric', 'Value', 'Status'],
            ['Total Products', str(len(products)), '✓'],
            ['Avg ACOS', f"{sum(acos_list)/len(acos_list):.1f}%", 'OK' if sum(acos_list)/len(acos_list) < 30 else 'Warning'],
            ['Avg Rating', f"{avg_rating:.1f}/5.0", 'OK' if avg_rating >= 4.0 else 'Warning'],
            ['Health Score', f"{avg_score:.0f}/100", 'OK' if avg_score >= 70 else 'Warning']]
        t = Table(summary_data, colWidths=[6*cm, 4*cm, 4*cm])
        t.setStyle(TableStyle([('BACKGROUND', (0,0), (-1,0), colors.HexColor('#FF9900')),
            ('TEXTCOLOR', (0,0), (-1,0), colors.white), ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
            ('ALIGN', (0,0), (-1,-1), 'CENTER'), ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, colors.HexColor('#f8f9fa')]),
            ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#dee2e6')), ('FONTSIZE', (0,0), (-1,-1), 10), ('PADDING', (0,0), (-1,-1), 8)]))
        story.append(t)
    story.append(Spacer(1, 0.5*cm))
    story.append(Paragraph("Product Details", heading_style))
    products_data = [['Product', 'Sales €', 'Spend €', 'ACOS %', 'Rating', 'Score']]
    for p in valid_products:
        acos = (p['cheltuieli'] / p['vanzari']) * 100
        score = calculate_score(p)
        products_data.append([p['nume'][:25], f"{p['vanzari']}€", f"{p['cheltuieli']}€", f"{acos:.1f}%", f"{p['rating']}/5.0", f"{score}/100"])
    t2 = Table(products_data, colWidths=[5*cm, 2.5*cm, 2.5*cm, 2*cm, 2*cm, 2*cm])
    t2.setStyle(TableStyle([('BACKGROUND', (0,0), (-1,0), colors.HexColor('#FF9900')),
        ('TEXTCOLOR', (0,0), (-1,0), colors.white), ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('ALIGN', (0,0), (-1,-1), 'CENTER'), ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, colors.HexColor('#f8f9fa')]),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#dee2e6')), ('FONTSIZE', (0,0), (-1,-1), 9), ('PADDING', (0,0), (-1,-1), 6)]))
    story.append(t2)
    story.append(Spacer(1, 0.5*cm))
    story.append(Paragraph("Generated by Agent Amazon — Powered by Claude AI | amazonanalyzer.org",
                           ParagraphStyle('Footer', parent=styles['Normal'], fontSize=8, textColor=colors.grey)))
    doc.build(story)
    buffer.seek(0)
    return buffer

def show_onboarding():
    st.markdown("## 👋 Welcome to Agent Amazon!")
    st.markdown("Let's set up your account in **3 simple steps**:")
    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown("### ✅ Step 1\n**Add your first product**\n\nEnter your ACOS, rating and sales.")
        if st.button("➕ Add first product", use_container_width=True, type="primary"):
            st.session_state.page = "Products"
            st.rerun()
    with col2:
        st.markdown("### 📊 Step 2\n**Analyze with AI**\n\nSee your Health Score and TOP 3 actions.")
    with col3:
        st.markdown("### 🤖 Step 3\n**Talk to AI Agent**\n\nThe agent knows your products and gives recommendations.")
        if st.button("🤖 Open AI Agent", use_container_width=True):
            st.session_state.page = "Agent"
            st.rerun()
    st.divider()
    col1, col2, col3 = st.columns(3)
    with col1: st.info("📊 **Full Dashboard**\nACOS, Rating, Health Score")
    with col2: st.info("🤖 **Personal AI Agent**\nDirect conversation with Claude")
    with col3: st.info("💬 **Review Analysis**\nIdentify problems quickly")

def display_saved_report(r):
    data_json = r['date_json']
    products_r = data_json.get('produse', [])
    unprofitable_campaigns = data_json.get('campanii_neprofitabile', [])
    profitable_campaigns = data_json.get('campanii_profitabile', [])
    neg_kw = data_json.get('negative_keywords', [])
    prof_kw = data_json.get('profit_keywords', [])
    summary = data_json.get('sumar', {})

    col1, col2, col3, col4 = st.columns(4)
    with col1: st.metric("Total Sales", f"€{summary.get('total_vanzari', 0):,.0f}")
    with col2: st.metric("Total PPC Spend", f"€{summary.get('total_cheltuieli', 0):,.0f}")
    with col3: st.metric("Total TACOS", f"{summary.get('tacos_total', 0):.1f}%")
    with col4: st.metric("Ad Sales", f"€{summary.get('vanzari_ppc', 0):,.0f}")

    col1, col2, col3, col4 = st.columns(4)
    with col1: st.metric("ACOS (like Amazon)", f"{summary.get('acos_amazon', 0):.1f}%")
    with col2: st.metric("Organic Sales", f"€{summary.get('vanzari_organice', 0):,.0f}")
    with col3: st.metric("% Organic Sales", f"{summary.get('pct_organice', 0):.1f}%")
    with col4: st.metric("Organic vs Ads", f"{summary.get('pct_organice', 0):.0f}% / {100-summary.get('pct_organice', 0):.0f}%")

    if products_r:
        st.divider()
        st.subheader("📦 ACOS and TACOS per Product")
        for row in products_r:
            acos = float(row.get('ACOS %', 0))
            tacos = float(row.get('TACOS %', 0))
            if acos > 40: emoji, status = "🔴", "UNPROFITABLE"
            elif acos > 25: emoji, status = "🟡", "WARNING"
            else: emoji, status = "🟢", "PROFITABLE"
            with st.expander(f"{emoji} {str(row.get('Title',''))[:50]} ({row.get('ASIN','')}) — {status}"):
                c1, c2, c3, c4 = st.columns(4)
                with c1: st.metric("Total Sales", f"€{float(row.get('vanzari_totale', 0)):,.0f}")
                with c2: st.metric("PPC Spend", f"€{float(row.get('cheltuieli_ppc', 0)):,.0f}")
                with c3: st.metric("ACOS", f"{acos:.1f}%")
                with c4: st.metric("TACOS", f"{tacos:.2f}%")

    if unprofitable_campaigns or profitable_campaigns:
        st.divider()
        st.subheader("📢 Campaign Analysis")
        col1, col2 = st.columns(2)
        with col1:
            st.markdown("#### 🔴 Unprofitable Campaigns")
            if unprofitable_campaigns:
                for c in unprofitable_campaigns:
                    st.warning(f"**{c['nume']}** — ACOS {c['acos']:.0f}% | €{c['cheltuieli']:.0f}")
            else:
                st.success("No unprofitable campaigns!")
        with col2:
            st.markdown("#### 🟢 Profitable Campaigns")
            for c in profitable_campaigns:
                st.success(f"**{c['nume']}** — ACOS {c['acos']:.0f}% | €{c['vanzari']:.0f}")

    if neg_kw or prof_kw:
        st.divider()
        st.subheader("🔍 Search Term Analysis")
        col1, col2 = st.columns(2)
        with col1:
            st.markdown("#### ❌ Negative Keywords")
            for kw in neg_kw:
                camp = f" | 📢 {kw.get('campanie', '')}" if kw.get('campanie') else ""
                st.error(f"**{kw['keyword']}** — {kw['clicks']:.0f} clicks | €{kw['spend']:.2f}{camp}")
        with col2:
            st.markdown("#### ✅ Profitable Keywords")
            for kw in prof_kw:
                camp = f" | 📢 {kw.get('campanie', '')}" if kw.get('campanie') else ""
                st.success(f"**{kw['keyword']}** — ACOS {kw['acos']:.0f}% | €{kw['sales']:.0f}{camp}")

@tool
def calculate_profit(sales: int, acos: float, product_price: float, product_cost: float) -> str:
    """Calculate monthly profit for an Amazon product"""
    ad_spend = sales * product_price * (acos / 100)
    total_revenue = sales * product_price
    total_cost = sales * product_cost
    profit = total_revenue - ad_spend - total_cost
    margin = (profit / total_revenue) * 100 if total_revenue > 0 else 0
    return f"Revenue: {total_revenue:.0f}€ | Ads: {ad_spend:.0f}€ | Product cost: {total_cost:.0f}€ | PROFIT: {profit:.0f}€ | Margin: {margin:.1f}% | {'✅ PROFITABLE' if profit > 0 else '❌ LOSS'}"

@tool
def calculate_optimal_acos(target_margin: float, product_cost: float, selling_price: float) -> str:
    """Calculate maximum ACOS for target margin"""
    gross_margin = ((selling_price - product_cost) / selling_price) * 100
    max_acos = gross_margin - target_margin
    return f"Gross margin: {gross_margin:.1f}% | Maximum recommended ACOS: {max_acos:.1f}%"

if not st.session_state.logged_in:
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.title("🛒 Agent Amazon")
        st.write("Automated Amazon product analysis powered by AI")
        tab1, tab2 = st.tabs(["🔑 Login", "📝 Register"])
        with tab1:
            email = st.text_input("Email", key="login_email")
            password = st.text_input("Password", type="password", key="login_pass")
            if st.button("Login", use_container_width=True):
                success, result = login_user(email, password)
                if success:
                    st.session_state.logged_in = True
                    st.session_state.user = result
                    st.rerun()
                else:
                    st.error("Incorrect email or password!")
            st.divider()
            st.markdown("**or**")
            if st.button("🔴 Continue with Google", use_container_width=True):
                try:
                    data = supabase.auth.sign_in_with_oauth({
                        "provider": "google",
                        "options": {"redirect_to": "https://amazonanalyzer.org/?login=google"}
                    })
                    st.markdown(f'<meta http-equiv="refresh" content="0;url={data.url}">', unsafe_allow_html=True)
                    st.markdown(f"[👉 Click here]({data.url})")
                except Exception as e:
                    st.error(f"Google error: {str(e)}")
        with tab2:
            email_reg = st.text_input("Email", key="reg_email")
            password_reg = st.text_input("Password", type="password", key="reg_pass")
            if st.button("Create account", use_container_width=True):
                success, message = register_user(email_reg, password_reg)
                if success:
                    st.success(message)
                else:
                    st.error(message)
else:
    result = supabase.table("produse").select("*").eq("user_id", st.session_state.user.id).execute()
    products = result.data
    is_pro = check_pro(st.session_state.user.id)
    valid_products = [p for p in products if p['vanzari'] > 0]
    alerts = sum(1 for p in valid_products if p['rating'] < 4.0 or (p['cheltuieli']/p['vanzari'])*100 >= 30)
    products_with_issues = sum(1 for p in valid_products if calculate_score(p) < 75)

    if len(valid_products) > 0:
        save_history(st.session_state.user.id, valid_products)

    with st.sidebar:
        st.title("🛒 Agent Amazon")
        st.write(f"👤 {st.session_state.user.email}")
        if alerts > 0:
            st.error(f"⚠️ {alerts} active alerts!")
        st.divider()
        st.markdown("### Navigation")
        if st.button(f"📊  Dashboard {'🔴' if alerts > 0 else ''}", use_container_width=True):
            st.session_state.page = "Dashboard"
        if st.button(f"📦  Products {'⚠️' if products_with_issues > 0 else ''}", use_container_width=True):
            st.session_state.page = "Products"
        if st.button("📈  Reports", use_container_width=True):
            st.session_state.page = "Reports"
        if st.button("💬  Reviews", use_container_width=True):
            st.session_state.page = "Reviews"
        if st.button("🤖  AI Agent", use_container_width=True):
            st.session_state.page = "Agent"
        if st.button("👤  Profile", use_container_width=True):
            st.session_state.page = "Profile"
        st.divider()
        if is_pro:
            st.success("⭐ Pro Plan Active")
        else:
            st.info("🆓 Free Plan\nMax 2 products")
            if st.button("⭐ Upgrade Pro — €29/month", use_container_width=True):
                success, url = create_checkout_session(
                    st.session_state.user.email, st.session_state.user.id,
                    success_url="https://amazonanalyzer.org?success=true",
                    cancel_url="https://amazonanalyzer.org?cancel=true"
                )
                if success:
                    st.markdown(f"[👉 Pay here]({url})")
        st.divider()
        if st.button("🚪 Logout", use_container_width=True):
            supabase.auth.sign_out()
            for key in list(st.session_state.keys()):
                del st.session_state[key]
            st.rerun()

    if "success" in st.query_params:
        activate_pro(st.session_state.user.id)
        st.success("🎉 Pro Plan activated!")

    page = st.session_state.page

    if page == "Dashboard":
        st.title("📊 Dashboard")
        if len(valid_products) == 0:
            show_onboarding()
        else:
            acos_list = [(p['cheltuieli'] / p['vanzari']) * 100 for p in valid_products]
            avg_rating = sum(p['rating'] for p in valid_products) / len(valid_products)
            avg_score = sum(calculate_score(p) for p in valid_products) / len(valid_products)
            avg_acos = sum(acos_list) / len(acos_list)
            benchmark = industry_benchmark()

            col1, col2, col3, col4 = st.columns(4)
            with col1: st.metric("Total Products", len(products))
            with col2: st.metric("Avg ACOS", f"{avg_acos:.1f}%")
            with col3: st.metric("Avg Rating", f"{avg_rating:.1f} ⭐")
            with col4:
                emoji_score, _ = score_color(avg_score)
                st.metric("Health Score", f"{avg_score:.0f}/100 {emoji_score}")

            if alerts > 0:
                st.warning(f"⚠️ You have {alerts} products that need attention!")

            st.divider()
            st.subheader("📈 Comparison with Industry Average")
            col1, col2, col3 = st.columns(3)
            with col1:
                diff_acos = avg_acos - benchmark['acos_avg']
                st.metric("Your ACOS vs Industry", f"{avg_acos:.1f}%",
                         delta=f"{diff_acos:+.1f}% vs {benchmark['acos_avg']}%", delta_color="inverse")
            with col2:
                diff_rating = avg_rating - benchmark['rating_avg']
                st.metric("Your Rating vs Industry", f"{avg_rating:.1f}",
                         delta=f"{diff_rating:+.1f} vs {benchmark['rating_avg']}", delta_color="normal")
            with col3:
                diff_score = avg_score - benchmark['score_avg']
                st.metric("Your Score vs Industry", f"{avg_score:.0f}/100",
                         delta=f"{diff_score:+.0f} vs {benchmark['score_avg']:.0f}", delta_color="normal")

            st.divider()
            st.subheader("📉 ACOS History per Product")
            for product in valid_products:
                history = get_history(st.session_state.user.id, product['id'])
                if len(history) > 1:
                    df_history = pd.DataFrame(history)
                    fig = px.line(df_history, x='data', y='acos',
                                 title=f"ACOS Evolution — {product['nume']}", markers=True)
                    fig.add_hline(y=30, line_dash="dash", line_color="red", annotation_text="30% limit")
                    st.plotly_chart(fig, use_container_width=True)
                else:
                    st.info(f"📦 {product['nume']} — History available after more days of data.")

            st.divider()
            col1, col2 = st.columns([4, 1])
            with col2:
                if st.button("📄 Export PDF", use_container_width=True):
                    with st.spinner("Generating report..."):
                        pdf_buffer = generate_pdf(valid_products, st.session_state.user.email)
                        st.download_button(label="⬇️ Download PDF", data=pdf_buffer,
                            file_name=f"amazon_report_{datetime.now().strftime('%Y%m%d')}.pdf",
                            mime="application/pdf", use_container_width=True)

            recommendations = generate_recommendations(valid_products)
            if recommendations:
                st.subheader("🎯 TOP 3 Actions for TODAY")
                for i, rec in enumerate(recommendations):
                    with st.expander(f"{rec['emoji']} {rec['priority']} — {rec['action']}"):
                        st.write(f"**Reason:** {rec['reason']}")
                        if st.button("🤖 Get detailed plan", key=f"rec_{i}"):
                            with st.spinner("Claude generating plan..."):
                                msg = client.messages.create(
                                    model="claude-haiku-4-5-20251001", max_tokens=200,
                                    messages=[{"role": "user", "content": f"Action plan in 3 steps for: {rec['action']}. Reason: {rec['reason']}"}]
                                )
                                st.write(msg.content[0].text)

            st.divider()
            st.subheader("💊 Product Health Score")
            for product in valid_products:
                score = calculate_score(product)
                emoji, _ = score_color(score)
                acos = (product['cheltuieli'] / product['vanzari']) * 100
                col1, col2, col3, col4 = st.columns([3, 1, 1, 1])
                with col1:
                    st.write(f"**{product['nume']}**")
                    st.progress(score / 100)
                with col2: st.metric("Score", f"{score} {emoji}")
                with col3: st.metric("Rating", product['rating'])
                with col4: st.metric("ACOS", f"{acos:.1f}%")

            st.divider()
            df = pd.DataFrame(valid_products)
            df['ACOS %'] = df.apply(lambda r: (r['cheltuieli']/r['vanzari'])*100, axis=1)
            df['Score'] = df.apply(lambda r: calculate_score(r), axis=1)
            col1, col2 = st.columns(2)
            with col1:
                fig = px.bar(df, x='nume', y='ACOS %', color='ACOS %',
                            color_continuous_scale=['green', 'yellow', 'red'], title="ACOS % per Product")
                fig.add_hline(y=30, line_dash="dash", line_color="red", annotation_text="30% limit")
                st.plotly_chart(fig, use_container_width=True)
            with col2:
                fig2 = px.bar(df, x='nume', y='Score', color='Score',
                             color_continuous_scale=['red', 'yellow', 'green'], title="Health Score")
                fig2.add_hline(y=70, line_dash="dash", line_color="orange", annotation_text="Recommended minimum")
                st.plotly_chart(fig2, use_container_width=True)

    elif page == "Products":
        st.title("📦 Your Products")
        tab1, tab2, tab3 = st.tabs(["➕ Add Manual", "🔗 Add from Link", "📊 Import Amazon Report"])

        with tab1:
            with st.expander("➕ Add product manually", expanded=True):
                name = st.text_input("Product name", key="manual_name")
                col1, col2 = st.columns(2)
                with col1:
                    sales = st.number_input("Monthly sales (€)", min_value=0, key="manual_sales")
                    spend = st.number_input("Ad spend (€)", min_value=0, key="manual_spend")
                with col2:
                    rating = st.number_input("Rating", min_value=0.0, max_value=5.0, step=0.1, key="manual_rating")
                if st.button("💾 Save product", use_container_width=True):
                    if not is_pro and len(products) >= 2:
                        st.warning("⚠️ 2 product limit on free plan. Upgrade to Pro!")
                    else:
                        supabase.table("produse").insert({
                            "user_id": st.session_state.user.id,
                            "nume": name, "vanzari": sales,
                            "cheltuieli": spend, "rating": rating
                        }).execute()
                        st.success("Product saved!")
                        st.rerun()

        with tab2:
            st.markdown("### 🔗 Add product from Amazon link")
            amazon_link = st.text_input("Amazon link", placeholder="https://www.amazon.es/dp/B08XYZ123...")
            if amazon_link:
                asin = extract_asin(amazon_link)
                if asin:
                    st.success(f"✅ ASIN detected: **{asin}**")
                    col1, col2 = st.columns(2)
                    with col1:
                        name_link = st.text_input("Product name", key="link_name")
                        sales_link = st.number_input("Monthly sales (€)", min_value=0, key="link_sales")
                        spend_link = st.number_input("Ad spend (€)", min_value=0, key="link_spend")
                    with col2:
                        rating_link = st.number_input("Rating", min_value=0.0, max_value=5.0, step=0.1, key="link_rating")
                        st.text_input("ASIN", value=asin, disabled=True)
                        st.selectbox("Marketplace", ["amazon.es", "amazon.de", "amazon.fr", "amazon.it", "amazon.co.uk", "amazon.com"])
                    if st.button("💾 Save product from link", use_container_width=True, type="primary"):
                        if not is_pro and len(products) >= 2:
                            st.warning("⚠️ 2 product limit on free plan!")
                        elif not name_link:
                            st.warning("⚠️ Enter the product name!")
                        else:
                            supabase.table("produse").insert({
                                "user_id": st.session_state.user.id,
                                "nume": f"{name_link} ({asin})",
                                "vanzari": sales_link,
                                "cheltuieli": spend_link,
                                "rating": rating_link
                            }).execute()
                            st.success(f"✅ Product {asin} saved!")
                            st.rerun()
                else:
                    st.error("❌ Could not extract ASIN!")

        with tab3:
            st.markdown("### 📊 Import Amazon Seller Central Report")
            st.info("""**How to download the report:**
1. Seller Central → Reports → Business Reports
2. Click **"Detail page sales and traffic by child item"**
3. Set the desired period
4. Click **"Download (.csv)"**""")
            csv_file = st.file_uploader("Upload Amazon CSV report", type="csv", key="amazon_csv")
            if csv_file is not None:
                try:
                    df_amazon = pd.read_csv(csv_file, sep=',', thousands=',', quotechar='"')
                    st.success(f"✅ {len(df_amazon)} rows detected")
                    st.dataframe(df_amazon[['(Child) ASIN', 'Title', 'Units ordered', 'Ordered Product Sales']].head(5) if '(Child) ASIN' in df_amazon.columns else df_amazon.head(5))
                    col1, col2 = st.columns(2)
                    with col1:
                        default_spend = st.number_input("Default spend (€)", min_value=0, value=0, key="import_spend")
                    with col2:
                        default_rating = st.number_input("Default rating", min_value=0.0, max_value=5.0, value=4.0, step=0.1, key="import_rating")
                    if st.button("🚀 Import all products", use_container_width=True, type="primary"):
                        if not is_pro and len(products) >= 2:
                            st.warning("⚠️ 2 product limit on free plan!")
                        else:
                            with st.spinner("Importing..."):
                                imported, errors = import_amazon_report(df_amazon, st.session_state.user.id, default_spend, default_rating)
                                st.success(f"✅ {imported} products imported!")
                                st.rerun()
                except Exception as e:
                    st.error(f"❌ Error: {str(e)}")

        if len(products) > 0:
            st.divider()
            st.subheader("Your Products")
            for product in products:
                score = calculate_score(product)
                emoji, _ = score_color(score)
                acos = (product['cheltuieli'] / product['vanzari']) * 100 if product['vanzari'] > 0 else 0
                col1, col2, col3 = st.columns([5, 1, 1])
                with col1:
                    st.write(f"{emoji} **{product['nume']}** — Rating: {product['rating']} | ACOS: {acos:.1f}% | Score: {score}/100")
                with col2:
                    if st.button("✏️ Edit", key=f"edit_{product['id']}"):
                        st.session_state[f"editing_{product['id']}"] = not st.session_state.get(f"editing_{product['id']}", False)
                with col3:
                    if st.button("🗑️ Delete", key=f"del_{product['id']}"):
                        supabase.table("produse").delete().eq("id", product['id']).execute()
                        st.success("Product deleted!")
                        st.rerun()

                if st.session_state.get(f"editing_{product['id']}", False):
                    st.session_state.setdefault(f"edit_name_{product['id']}", product['nume'])
                    st.session_state.setdefault(f"edit_sales_{product['id']}", int(product['vanzari']))
                    st.session_state.setdefault(f"edit_spend_{product['id']}", int(product['cheltuieli']))
                    st.session_state.setdefault(f"edit_rating_{product['id']}", float(product['rating']))

                    col1, col2 = st.columns(2)
                    with col1:
                        st.session_state[f"edit_name_{product['id']}"] = st.text_input(
                            "Name", value=st.session_state[f"edit_name_{product['id']}"],
                            key=f"inp_name_{product['id']}")
                        st.session_state[f"edit_sales_{product['id']}"] = st.number_input(
                            "Sales (€)", min_value=0,
                            value=st.session_state[f"edit_sales_{product['id']}"],
                            key=f"inp_sales_{product['id']}")
                    with col2:
                        st.session_state[f"edit_spend_{product['id']}"] = st.number_input(
                            "Ad Spend (€)", min_value=0,
                            value=st.session_state[f"edit_spend_{product['id']}"],
                            key=f"inp_spend_{product['id']}")
                        st.session_state[f"edit_rating_{product['id']}"] = st.number_input(
                            "Rating", min_value=0.0, max_value=5.0, step=0.1,
                            value=st.session_state[f"edit_rating_{product['id']}"],
                            key=f"inp_rating_{product['id']}")

                    if st.button("💾 Save", key=f"save_{product['id']}", type="primary"):
                        supabase.table("produse").update({
                            "nume": st.session_state[f"edit_name_{product['id']}"],
                            "vanzari": st.session_state[f"edit_sales_{product['id']}"],
                            "cheltuieli": st.session_state[f"edit_spend_{product['id']}"],
                            "rating": st.session_state[f"edit_rating_{product['id']}"]
                        }).eq("id", product['id']).execute()
                        st.session_state[f"editing_{product['id']}"] = False
                        st.success("✅ Saved!")
                        st.rerun()

            st.divider()
            if st.button("🔍 Analyze all products", use_container_width=True):
                for product in products:
                    if product['vanzari'] == 0:
                        continue
                    score = calculate_score(product)
                    emoji, _ = score_color(score)
                    acos = (product['cheltuieli'] / product['vanzari']) * 100
                    with st.expander(f"{emoji} {product['nume']} — Score {score}/100 | ACOS {acos:.1f}%"):
                        if product['rating'] < 4.0:
                            st.warning(f"⚠️ Low rating: {product['rating']}")
                            with st.spinner("Claude analyzing..."):
                                msg = client.messages.create(
                                    model="claude-haiku-4-5-20251001", max_tokens=150,
                                    messages=[{"role": "user", "content": f"2 concrete actions for '{product['nume']}' with rating {product['rating']}: "}]
                                )
                                st.write(msg.content[0].text)
                        else:
                            st.success(f"✅ Good rating: {product['rating']}")

    elif page == "Reports":
        st.title("📈 Monthly Reports")
        st.info("Upload your sales report and PPC report for the same month to calculate real ACOS and TACOS.")

        months_display = {
            "2026-06": "June 2026", "2026-05": "May 2026", "2026-04": "April 2026",
            "2026-03": "March 2026", "2026-02": "February 2026", "2026-01": "January 2026",
            "2025-12": "December 2025", "2025-11": "November 2025", "2025-10": "October 2025",
            "2025-09": "September 2025", "2025-08": "August 2025", "2025-07": "July 2025",
            "2025-06": "June 2025", "2025-05": "May 2025", "2025-04": "April 2025",
            "2025-03": "March 2025", "2025-02": "February 2025", "2025-01": "January 2025"
        }
        selected_month = st.selectbox("Select month", list(months_display.keys()), format_func=lambda x: months_display[x])

        col1, col2 = st.columns(2)
        with col1:
            csv_sales = st.file_uploader("📦 Sales Report (CSV)", type="csv", key="csv_vanzari", help="Seller Central → Business Reports → Detail page sales and traffic by child item")
        with col2:
            csv_ppc = st.file_uploader("📢 PPC Report (CSV/XLSX)", type=["csv", "xlsx"], key="csv_ppc", help="Amazon Advertising → Sponsored ads reports → Advertised product report")

        st.divider()
        csv_search = st.file_uploader("🔍 Search Term Report - Optional (CSV/XLSX)", type=["csv", "xlsx"], key="csv_search", help="Amazon Advertising → Sponsored ads reports → Search term report")

        if csv_sales and csv_ppc:
            if st.button("🔍 Analyze", use_container_width=True, type="primary"):
                with st.spinner("Analyzing data..."):
                    try:
                        df_sales = pd.read_csv(csv_sales, sep=',', thousands=',', quotechar='"')
                        if csv_ppc.name.endswith('.xlsx'):
                            df_ppc = pd.read_excel(csv_ppc, engine='openpyxl')
                        else:
                            df_ppc = pd.read_csv(csv_ppc, sep='\t')

                        df_ppc['Spend_clean'] = df_ppc['Spend'].apply(clean_value)
                        df_ppc['Sales_clean'] = df_ppc['7 Day Total Sales'].apply(clean_value)

                        ppc_per_asin = df_ppc.groupby('Advertised ASIN').agg(
                            cheltuieli_ppc=('Spend_clean', 'sum'),
                            vanzari_ppc=('Sales_clean', 'sum')
                        ).reset_index()

                        df_sales['Sales_clean'] = df_sales['Ordered Product Sales'].apply(clean_value)
                        df_sales = df_sales[['(Child) ASIN', 'Title', 'Sales_clean']].copy()
                        df_sales.columns = ['ASIN', 'Title', 'vanzari_totale']
                        df_sales = df_sales[df_sales['vanzari_totale'] > 0]

                        df_merge = df_sales.merge(ppc_per_asin, left_on='ASIN', right_on='Advertised ASIN', how='left')
                        df_merge['cheltuieli_ppc'] = df_merge['cheltuieli_ppc'].fillna(0)
                        df_merge['vanzari_ppc'] = df_merge['vanzari_ppc'].fillna(0)
                        df_merge['ACOS %'] = df_merge.apply(
                            lambda r: (r['cheltuieli_ppc'] / r['vanzari_ppc'] * 100) if r['vanzari_ppc'] > 0 else 0, axis=1)
                        df_merge['TACOS %'] = df_merge.apply(
                            lambda r: (r['cheltuieli_ppc'] / r['vanzari_totale'] * 100) if r['vanzari_totale'] > 0 else 0, axis=1)

                        total_sales = df_merge['vanzari_totale'].sum()
                        total_spend = df_merge['cheltuieli_ppc'].sum()
                        total_ad_sales = df_merge['vanzari_ppc'].sum()
                        tacos_total = (total_spend / total_sales * 100) if total_sales > 0 else 0
                        acos_amazon = (total_spend / total_ad_sales * 100) if total_ad_sales > 0 else 0
                        organic_sales = total_sales - total_ad_sales
                        pct_organic = (organic_sales / total_sales * 100) if total_sales > 0 else 0

                        st.divider()
                        st.subheader(f"📊 Results — {months_display[selected_month]}")
                        col1, col2, col3, col4 = st.columns(4)
                        with col1: st.metric("Total Sales", f"€{total_sales:,.0f}")
                        with col2: st.metric("Total PPC Spend", f"€{total_spend:,.0f}")
                        with col3: st.metric("Total TACOS", f"{tacos_total:.1f}%", help="PPC Spend / Total monthly sales")
                        with col4: st.metric("ACOS (like Amazon)", f"{acos_amazon:.1f}%", help="PPC Spend / Ad sales — identical to Amazon")

                        col1, col2, col3, col4 = st.columns(4)
                        with col1: st.metric("Ad Sales", f"€{total_ad_sales:,.0f}", help="Same as Amazon Campaign Manager")
                        with col2: st.metric("Organic Sales", f"€{organic_sales:,.0f}", help="Sales without ads")
                        with col3: st.metric("% Organic Sales", f"{pct_organic:.1f}%")
                        with col4: st.metric("Organic vs Ads", f"{pct_organic:.0f}% / {100-pct_organic:.0f}%")

                        st.info("ℹ️ **ACOS** = PPC Spend / Ad sales (7 days). **TACOS** = PPC Spend / TOTAL monthly sales — more accurate for real business analysis.")

                        st.divider()
                        st.subheader("📦 ACOS and TACOS per Product")
                        for _, row in df_merge.iterrows():
                            acos = row['ACOS %']
                            tacos = row['TACOS %']
                            if acos > 40: emoji, status = "🔴", "UNPROFITABLE"
                            elif acos > 25: emoji, status = "🟡", "WARNING"
                            else: emoji, status = "🟢", "PROFITABLE"
                            with st.expander(f"{emoji} {row['Title'][:50]} ({row['ASIN']}) — {status}"):
                                c1, c2, c3, c4 = st.columns(4)
                                with c1: st.metric("Total Sales", f"€{row['vanzari_totale']:,.0f}")
                                with c2: st.metric("PPC Spend", f"€{row['cheltuieli_ppc']:,.0f}")
                                with c3: st.metric("ACOS", f"{acos:.1f}%")
                                with c4: st.metric("TACOS", f"{tacos:.2f}%")

                        st.divider()
                        st.subheader("📢 Campaign Analysis")
                        df_ppc['ACOS_camp'] = df_ppc.apply(
                            lambda r: (clean_value(r['Spend']) / clean_value(r['7 Day Total Sales']) * 100)
                            if clean_value(r['7 Day Total Sales']) > 0 else 999, axis=1)

                        unprofitable_list = []
                        profitable_list = []

                        col1, col2 = st.columns(2)
                        with col1:
                            st.markdown("#### 🔴 Unprofitable Campaigns (ACOS > 40%)")
                            unprofitable = df_ppc[(df_ppc['ACOS_camp'] > 40) & (df_ppc['ACOS_camp'] < 999)].sort_values('ACOS_camp', ascending=False)
                            if len(unprofitable) > 0:
                                for _, camp in unprofitable.iterrows():
                                    st.warning(f"**{camp['Campaign Name']}** — ACOS {camp['ACOS_camp']:.0f}% | €{clean_value(camp['Spend']):.0f}")
                                    unprofitable_list.append({'nume': camp['Campaign Name'], 'acos': camp['ACOS_camp'], 'cheltuieli': clean_value(camp['Spend'])})
                            else:
                                st.success("No unprofitable campaigns! 🎉")
                        with col2:
                            st.markdown("#### 🟢 Profitable Campaigns (ACOS < 25%)")
                            profitable = df_ppc[(df_ppc['ACOS_camp'] < 25) & (df_ppc['ACOS_camp'] > 0)].sort_values('ACOS_camp')
                            for _, camp in profitable.iterrows():
                                st.success(f"**{camp['Campaign Name']}** — ACOS {camp['ACOS_camp']:.0f}% | €{clean_value(camp['7 Day Total Sales']):.0f}")
                                profitable_list.append({'nume': camp['Campaign Name'], 'acos': camp['ACOS_camp'], 'vanzari': clean_value(camp['7 Day Total Sales'])})

                        neg_kw_list = []
                        prof_kw_list = []

                        if csv_search is not None:
                            st.divider()
                            st.subheader("🔍 Search Term Analysis")
                            if csv_search.name.endswith('.xlsx'):
                                df_search = pd.read_excel(csv_search, engine='openpyxl')
                            else:
                                df_search = pd.read_csv(csv_search, sep='\t')

                            df_search['Spend_s'] = df_search['Spend'].apply(clean_value)
                            df_search['Sales_s'] = df_search['7 Day Total Sales'].apply(clean_value)
                            df_search['Clicks_s'] = pd.to_numeric(df_search['Clicks'], errors='coerce').fillna(0)

                            search_agg = df_search.groupby('Customer Search Term').agg(
                                clicks=('Clicks_s', 'sum'),
                                spend=('Spend_s', 'sum'),
                                sales=('Sales_s', 'sum')
                            ).reset_index()

                            search_agg['ACOS'] = search_agg.apply(
                                lambda r: (r['spend'] / r['sales'] * 100) if r['sales'] > 0 else 999, axis=1)

                            col1, col2 = st.columns(2)
                            with col1:
                                st.markdown("#### ❌ Negative Keywords — Block them!")
                                negative_kw = search_agg[
                                    (search_agg['clicks'] >= 3) &
                                    (search_agg['sales'] == 0) &
                                    (search_agg['spend'] > 0.5)
                                ].sort_values('spend', ascending=False).head(15)
                                for _, kw in negative_kw.iterrows():
                                    camp_name = df_search[df_search['Customer Search Term'] == kw['Customer Search Term']]['Campaign Name'].iloc[0] if len(df_search[df_search['Customer Search Term'] == kw['Customer Search Term']]) > 0 else "N/A"
                                    st.error(f"**{kw['Customer Search Term']}** — {kw['clicks']:.0f} clicks | €{kw['spend']:.2f} | 0 sales | 📢 {camp_name}")
                                    neg_kw_list.append({'keyword': kw['Customer Search Term'], 'clicks': kw['clicks'], 'spend': kw['spend'], 'campanie': camp_name})

                            with col2:
                                st.markdown("#### ✅ Profitable Keywords — Increase Budget!")
                                profit_kw = search_agg[
                                    (search_agg['sales'] > 0) &
                                    (search_agg['ACOS'] < 25) &
                                    (search_agg['ACOS'] > 0)
                                ].sort_values('sales', ascending=False).head(15)
                                for _, kw in profit_kw.iterrows():
                                    camp_name = df_search[df_search['Customer Search Term'] == kw['Customer Search Term']]['Campaign Name'].iloc[0] if len(df_search[df_search['Customer Search Term'] == kw['Customer Search Term']]) > 0 else "N/A"
                                    st.success(f"**{kw['Customer Search Term']}** — ACOS {kw['ACOS']:.0f}% | €{kw['sales']:.0f} | 📢 {camp_name}")
                                    prof_kw_list.append({'keyword': kw['Customer Search Term'], 'acos': kw['ACOS'], 'sales': kw['sales'], 'campanie': camp_name})

                        complete_report = {
                            'sumar': {
                                'total_vanzari': total_sales,
                                'total_cheltuieli': total_spend,
                                'tacos_total': tacos_total,
                                'vanzari_ppc': total_ad_sales,
                                'acos_amazon': acos_amazon,
                                'vanzari_organice': organic_sales,
                                'pct_organice': pct_organic
                            },
                            'produse': df_merge[['ASIN', 'Title', 'vanzari_totale', 'cheltuieli_ppc', 'ACOS %', 'TACOS %']].to_dict('records'),
                            'campanii_neprofitabile': unprofitable_list,
                            'campanii_profitabile': profitable_list,
                            'negative_keywords': neg_kw_list,
                            'profit_keywords': prof_kw_list
                        }

                        supabase.table("rapoarte_lunare").insert({
                            "user_id": st.session_state.user.id,
                            "luna": f"{selected_month}-01",
                            "tip": "complet",
                            "date_json": complete_report
                        }).execute()
                        st.success(f"✅ Report {months_display[selected_month]} saved successfully!")

                    except Exception as e:
                        st.error(f"❌ Error: {str(e)}")

        elif csv_sales and not csv_ppc:
            st.info("📢 Please upload the PPC report too!")
        elif csv_ppc and not csv_sales:
            st.info("📦 Please upload the sales report too!")

        st.divider()
        st.subheader("📅 Saved Reports History")
        saved_reports = supabase.table("rapoarte_lunare").select("*").eq("user_id", st.session_state.user.id).order("created_at", desc=True).execute()
        if saved_reports.data:
            for r in saved_reports.data:
                col1, col2, col3 = st.columns([3, 1, 1])
                with col1:
                    st.write(f"✅ {r['luna'][:7]} — saved on {r['created_at'][:10]}")
                with col2:
                    if st.button("👁️ View", key=f"view_{r['id']}"):
                        st.session_state[f"show_report_{r['id']}"] = not st.session_state.get(f"show_report_{r['id']}", False)
                with col3:
                    if st.button("🗑️ Delete", key=f"del_report_{r['id']}"):
                        supabase.table("rapoarte_lunare").delete().eq("id", r['id']).execute()
                        st.success("Report deleted!")
                        st.rerun()
                if st.session_state.get(f"show_report_{r['id']}", False):
                    display_saved_report(r)
        else:
            st.info("No saved reports yet.")

    elif page == "Reviews":
        st.title("💬 Review Analysis")
        file = st.file_uploader("Upload CSV with reviews", type="csv")
        if file is not None:
            df_reviews = pd.read_csv(file)
            st.write(f"Reviews loaded: {len(df_reviews)}")
            st.dataframe(df_reviews, use_container_width=True)
            if st.button("🤖 Analyze negative reviews", use_container_width=True):
                negative = df_reviews[df_reviews['rating'] <= 2]
                for index, row in negative.iterrows():
                    with st.expander(f"⚠️ {row['produs']} — {row['review'][:50]}..."):
                        with st.spinner("Claude analyzing..."):
                            msg = client.messages.create(
                                model="claude-haiku-4-5-20251001", max_tokens=150,
                                messages=[{"role": "user", "content": f"Concrete solution in 2 lines: '{row['review']}'"}]
                            )
                            st.write(msg.content[0].text)

    elif page == "Agent":
        st.title("🤖 Amazon AI Agent")
        st.info("💡 Ask the agent: 'Calculate profit for 500 sales, ACOS 30%, price €15, cost €5'")
        if "agent_messages" not in st.session_state:
            st.session_state.agent_messages = []
        for msg in st.session_state.agent_messages:
            with st.chat_message(msg["role"]):
                st.write(msg["content"])
        if prompt := st.chat_input("Ask your Amazon agent..."):
            st.session_state.agent_messages.append({"role": "user", "content": prompt})
            with st.chat_message("user"):
                st.write(prompt)
            with st.chat_message("assistant"):
                with st.spinner("Agent analyzing..."):
                    model_lc = ChatAnthropic(model="claude-haiku-4-5-20251001", api_key=api_key)
                    tools = [calculate_profit, calculate_optimal_acos]
                    scores = {p['nume']: calculate_score(p) for p in valid_products}
                    lc_messages = [SystemMessage(content=f"""You are an Amazon expert helping sellers optimize their business.
                        Always respond in English. Be direct and give concrete actions.
                        User's products: {valid_products}
                        Health scores: {scores}
                        Industry benchmark: {industry_benchmark()}
                        Use tools for financial calculations.""")]
                    for msg in st.session_state.agent_messages:
                        if msg["role"] == "user":
                            lc_messages.append(HumanMessage(content=msg["content"]))
                    try:
                        agent = create_react_agent(model=model_lc, tools=tools)
                        result = agent.invoke({"messages": lc_messages})
                        response_text = result["messages"][-1].content
                    except Exception:
                        response = model_lc.invoke(lc_messages)
                        response_text = response.content
                    st.write(response_text)
                    st.session_state.agent_messages.append({"role": "assistant", "content": response_text})

    elif page == "Profile":
        st.title("👤 My Profile")
        col1, col2 = st.columns([1, 2])
        with col1:
            st.markdown(f"""
            <div style="background:#f8f9fa; padding:2rem; border-radius:12px; text-align:center;">
                <div style="font-size:4rem;">👤</div>
                <h3>{st.session_state.user.email}</h3>
                <p style="color:#888;">Member since {datetime.now().strftime('%B %Y')}</p>
            </div>
            """, unsafe_allow_html=True)
        with col2:
            st.subheader("Account Information")
            st.write(f"**Email:** {st.session_state.user.email}")
            st.write(f"**Plan:** {'⭐ Pro' if is_pro else '🆓 Free'}")
            st.write(f"**Active products:** {len(products)}")
            st.write(f"**Account ID:** `{str(st.session_state.user.id)[:8]}...`")
            st.divider()
            st.subheader("Statistics")
            if len(valid_products) > 0:
                acos_list = [(p['cheltuieli'] / p['vanzari']) * 100 for p in valid_products]
                avg_score = sum(calculate_score(p) for p in valid_products) / len(valid_products)
                col1, col2, col3 = st.columns(3)
                with col1: st.metric("Products", len(products))
                with col2: st.metric("Avg ACOS", f"{sum(acos_list)/len(acos_list):.1f}%")
                with col3:
                    emoji, _ = score_color(avg_score)
                    st.metric("Avg Score", f"{avg_score:.0f} {emoji}")
            else:
                st.info("Add products to see your statistics.")
            st.divider()
            if not is_pro:
                st.subheader("🚀 Upgrade to Pro")
                if st.button("⭐ Upgrade to Pro — €29/month", use_container_width=True, type="primary"):
                    success, url = create_checkout_session(
                        st.session_state.user.email, st.session_state.user.id,
                        success_url="https://amazonanalyzer.org?success=true",
                        cancel_url="https://amazonanalyzer.org?cancel=true"
                    )
                    if success:
                        st.markdown(f"[👉 Pay here]({url})")
            else:
                st.success("⭐ You're on Pro Plan — you have access to all features!")