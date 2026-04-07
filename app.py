import streamlit as st
import feedparser
import google.generativeai as genai
from groq import Groq
import json
import sqlite3
from datetime import datetime

# ==========================================
# 1. CẤU HÌNH GIAO DIỆN & DATABASE
# ==========================================
st.set_page_config(page_title="Radar Chiến Lược Toàn Cầu v12.4", layout="wide", page_icon="📡")

# !!! QUAN TRỌNG: SỬA EMAIL NÀY THÀNH EMAIL CỦA BẠN !!!
MASTER_ADMIN_EMAIL = "admin@gmail.com"

def init_db():
    conn = sqlite3.connect('radar_database.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS api_keys (id INTEGER PRIMARY KEY, platform TEXT, key_value TEXT UNIQUE)''')
    c.execute('''CREATE TABLE IF NOT EXISTS reports (id INTEGER PRIMARY KEY AUTOINCREMENT, run_time TEXT, html_content TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, email TEXT UNIQUE, role TEXT)''')
    
    c.execute("SELECT COUNT(*) FROM users WHERE role='admin'")
    if c.fetchone()[0] == 0:
        c.execute("INSERT OR IGNORE INTO users (email, role) VALUES (?, 'admin')", (MASTER_ADMIN_EMAIL,))
    conn.commit()
    conn.close()

init_db()

# --- Các hàm xử lý Database ---
def add_user(email, role="user"):
    try:
        conn = sqlite3.connect('radar_database.db'); c = conn.cursor()
        c.execute("INSERT INTO users (email, role) VALUES (?, ?)", (email.strip(), role))
        conn.commit(); conn.close(); return True
    except sqlite3.IntegrityError: return False

def get_all_users():
    conn = sqlite3.connect('radar_database.db'); c = conn.cursor()
    c.execute("SELECT email, role FROM users ORDER BY role, email")
    users = c.fetchall(); conn.close(); return users

def check_user_access(email):
    conn = sqlite3.connect('radar_database.db'); c = conn.cursor()
    c.execute("SELECT role FROM users WHERE email=?", (email.strip(),))
    result = c.fetchone(); conn.close()
    return result[0] if result else None

def add_api_key(platform, key_value):
    conn = sqlite3.connect('radar_database.db'); c = conn.cursor()
    c.execute("DELETE FROM api_keys WHERE platform=?")
    c.execute("INSERT INTO api_keys (platform, key_value) VALUES (?, ?)", (platform, key_value.strip()))
    conn.commit(); conn.close()

def get_api_key(platform):
    conn = sqlite3.connect('radar_database.db'); c = conn.cursor()
    c.execute("SELECT key_value FROM api_keys WHERE platform=? ORDER BY id DESC LIMIT 1", (platform,))
    res = c.fetchone(); conn.close()
    return res[0] if res else None

def reset_all_api_keys():
    conn = sqlite3.connect('radar_database.db'); c = conn.cursor()
    c.execute("DELETE FROM api_keys")
    conn.commit(); conn.close()

def save_report_to_db(html_content):
    conn = sqlite3.connect('radar_database.db'); c = conn.cursor()
    run_time = datetime.now().strftime("%H:%M - %d/%m/%Y")
    c.execute("INSERT INTO reports (run_time, html_content) VALUES (?, ?)", (run_time, html_content))
    conn.commit()
    # Đã sửa lỗi SQL OFFSET
    c.execute("SELECT id FROM reports ORDER BY id DESC LIMIT -1 OFFSET 20")
    for row in c.fetchall(): c.execute("DELETE FROM reports WHERE id=?", (row[0],))
    conn.commit(); conn.close()

def get_report_history():
    conn = sqlite3.connect('radar_database.db'); c = conn.cursor()
    c.execute("SELECT id, run_time, html_content FROM reports ORDER BY id DESC")
    records = c.fetchall(); conn.close(); return records

# CSS Giao diện
st.markdown("""
<style>
    .news-card { background: #fff; padding: 18px; border-radius: 10px; margin-bottom: 15px; border-left: 5px solid #0056b3; box-shadow: 0 4px 6px rgba(0,0,0,0.05); border: 1px solid #eee; }
    .news-category { font-size: 10px; font-weight: bold; background: #212529; color: white; padding: 2px 8px; border-radius: 3px; }
    .news-title-link { font-size: 17px; font-weight: bold; color: #0056b3; text-decoration: none; display: block; margin-bottom: 8px; margin-top: 8px; }
    .news-insight { font-size: 13px; font-style: italic; color: #155724; background: #d4edda; padding: 10px; border-radius: 5px; }
    .market-outlook { background: #111; color: #00ff41; padding: 20px; border-radius: 8px; font-family: monospace; white-space: pre-wrap; }
</style>
""", unsafe_allow_html=True)

# ==========================================
# 2. HỆ THỐNG ĐĂNG NHẬP
# ==========================================
if 'logged_in' not in st.session_state: st.session_state.logged_in = False
if 'user_email' not in st.session_state: st.session_state.user_email = ""
if 'is_admin' not in st.session_state: st.session_state.is_admin = False

if not st.session_state.logged_in:
    st.title("🔐 Cổng Đăng Nhập Radar")
    with st.form("login_form"):
        email = st.text_input("Nhập Gmail của bạn:")
        if st.form_submit_button("Đăng nhập"):
            user_role = check_user_access(email)
            if user_role:
                st.session_state.logged_in = True
                st.session_state.user_email = email
                st.session_state.is_admin = (user_role == "admin")
                st.rerun()
            else: st.error("Tài khoản chưa được cấp quyền.")
    st.stop()

# Thanh bên (Sidebar)
st.sidebar.success(f"👤 {st.session_state.user_email}")
if st.sidebar.button("Đăng xuất"):
    st.session_state.logged_in = False; st.rerun()

current_groq_key = get_api_key("GROQ")
current_gemini_key = get_api_key("GEMINI")

# Menu Admin
if st.session_state.is_admin:
    st.sidebar.markdown("---")
    st.sidebar.header("👑 Admin Control")
    with st.sidebar.expander("🔑 Quản lý API Keys"):
        if current_groq_key and current_gemini_key:
            st.success("✅ Đã có API Key")
            if st.button("🔄 Thay đổi Keys"): reset_all_api_keys(); st.rerun()
        else:
            new_groq = st.text_input("Groq Key:", type="password")
            new_gemini = st.text_input("Gemini Key:", type="password")
            if st.button("Lưu Keys"):
                if new_groq and new_gemini:
                    add_api_key("GROQ", new_groq); add_api_key("GEMINI", new_gemini); st.rerun()

    with st.sidebar.expander("👥 Người dùng"):
        u_email = st.text_input("Thêm Email:")
        u_role = st.selectbox("Quyền:", ["user", "admin"])
        if st.button("Thêm"):
            if add_user(u_email, u_role): st.success("Xong!"); st.rerun()

st.sidebar.markdown("---")
st.sidebar.header("🗂️ Lịch sử Báo cáo")
for r_id, r_time, r_html in get_report_history():
    with st.sidebar.expander(f"🕒 {r_time}"):
        st.download_button("📥 Tải HTML", data=r_html, file_name=f"Radar_{r_id}.html", mime="text/html", key=f"dl_{r_id}")

# ==========================================
# 3. XỬ LÝ DỮ LIỆU
# ==========================================
RSS_FEEDS = {
    "Mỹ 🇺🇸": ["https://rss.nytimes.com/services/xml/rss/nyt/World.xml"],
    "Châu Âu 🇪🇺": ["http://feeds.bbci.co.uk/news/world/europe/rss.xml"],
    "Trung Quốc 🇨🇳": ["https://www.scmp.com/rss/318198/feed"],
    "Việt Nam 🇻🇳": ["https://vnexpress.net/rss/the-gioi.rss"]
}

def groq_analyze(api_key, raw_data, region, topics, top_n):
    client = Groq(api_key=api_key)
    prompt = f"""
    Lọc {top_n} tin từ vùng {region} về {','.join(topics)}.
    YÊU CẦU: DỊCH 100% SANG TIẾNG VIỆT (Tiêu đề, Tóm tắt, Nhận định).
    Trả về JSON: {{'data': [{{'cat':'Lĩnh vực','src':'Tên báo (VD: CNN)','tit':'Tiêu đề VN','lnk':'Link','brf':'Tóm tắt VN','ins':'Nhận định VN'}}]}}
    Dữ liệu: {json.dumps(raw_data)}
    """
    try:
        response = client.chat.completions.create(
            messages=[
                {"role": "system", "content": "You are a professional news analyst. Output strictly JSON in VIETNAMESE language."},
                {"role": "user", "content": prompt}
            ],
            model="llama-3.3-70b-versatile",
            temperature=0.1,
            response_format={"type": "json_object"}
        )
        return json.loads(response.choices[0].message.content).get("data", [])
    except Exception as e: return [{"cat": "Lỗi", "tit": "Lỗi API", "brf": str(e)}]

def generate_html_report(news_data, outlook):
    now = datetime.now().strftime("%H:%M - %d/%m/%Y")
    html = f"<html><body style='font-family:sans-serif;padding:30px'><h1>Báo Cáo Radar {now}</h1>"
    html += f"<div style='background:#f4f4f4;padding:20px'><h3>Nhận định vĩ mô:</h3>{outlook}</div>"
    for reg, items in news_data.items():
        html += f"<h2>{reg}</h2>"
        for i in items:
            html += f"<div style='margin-bottom:15px'><b>[{i.get('cat')}] {i.get('src')}</b><br><a href='{i.get('lnk')}'>{i.get('tit')}</a><p>{i.get('brf')}</p></div>"
    return html + "</body></html>"

# ==========================================
# 4. GIAO DIỆN CHÍNH
# ==========================================
st.title("🌍 Radar Chiến Lược Toàn Cầu")

regions = st.sidebar.multiselect("Vùng:", list(RSS_FEEDS.keys()), default=["Mỹ 🇺🇸", "Việt Nam 🇻🇳"])
topics = st.sidebar.multiselect("Lĩnh vực:", ["Kinh tế", "Chính trị", "Công nghệ"], default=["Kinh tế"])

if st.sidebar.button("🚀 CHẠY RADAR MỚI", type="primary", use_container_width=True):
    if not current_groq_key or not current_gemini_key:
        st.error("Vui lòng nhập API Key trong phần Admin.")
    else:
        with st.spinner("Đang quét dữ liệu toàn cầu..."):
            st.session_state.news_store = {}
            for reg in regions:
                raw = []
                for url in RSS_FEEDS[reg]:
                    feed = feedparser.parse(url)
                    for e in feed.entries[:10]:
                        raw.append({"raw_title": e.get('title',''), "link": e.get('link','#'), "summary": e.get('summary','')[:200]})
                st.session_state.news_store[reg] = groq_analyze(current_groq_key, raw, reg, topics, 5)
            
            genai.configure(api_key=current_gemini_key)
            model = genai.GenerativeModel('gemini-1.5-flash')
            st.session_state.outlook_store = model.generate_content(f"Dựa trên dữ liệu này, hãy viết nhận định vĩ mô bằng tiếng Việt: {json.dumps(st.session_state.news_store)}").text
            
            save_report_to_db(generate_html_report(st.session_state.news_store, st.session_state.outlook_store))
            st.rerun()

if "news_store" in st.session_state:
    for reg, items in st.session_state.news_store.items():
        st.subheader(f"📍 {reg}")
        for i in items:
            st.markdown(f"""<div class="news-card">
                <span class="news-category">{i.get('cat')}</span> <b>{i.get('src')}</b>
                <a class="news-title-link" href="{i.get('lnk')}">{i.get('tit')}</a>
                <p>{i.get('brf')}</p>
                <div class="news-insight">💡 {i.get('ins')}</div>
            </div>""", unsafe_allow_html=True)
    
    st.markdown("### 📡 NHẬN ĐỊNH VĨ MÔ")
    st.markdown(f'<div class="market-outlook">{st.session_state.outlook_store}</div>', unsafe_allow_html=True)
