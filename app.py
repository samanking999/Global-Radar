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
st.set_page_config(page_title="Radar Chiến Lược Toàn Cầu v12.8", layout="wide", page_icon="📡")

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

# --- Các hàm Database (Giữ nguyên từ bản 12.7) ---
def add_user(email, role="user"):
    try:
        conn = sqlite3.connect('radar_database.db'); c = conn.cursor()
        c.execute("INSERT INTO users (email, role) VALUES (?, ?)", (email.strip().lower(), role))
        conn.commit(); conn.close(); return True
    except sqlite3.IntegrityError: return False

def get_all_users():
    conn = sqlite3.connect('radar_database.db'); c = conn.cursor()
    c.execute("SELECT email, role FROM users ORDER BY role, email")
    users = c.fetchall(); conn.close(); return users

def check_user_access(email):
    conn = sqlite3.connect('radar_database.db'); c = conn.cursor()
    c.execute("SELECT role FROM users WHERE email=?", (email.strip().lower(),))
    result = c.fetchone(); conn.close()
    return result[0] if result else None

def add_api_key(platform, key_value):
    conn = sqlite3.connect('radar_database.db'); c = conn.cursor()
    c.execute("DELETE FROM api_keys WHERE platform=?", (platform,))
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
    c.execute("SELECT id FROM reports ORDER BY id DESC LIMIT -1 OFFSET 20")
    for row in c.fetchall(): c.execute("DELETE FROM reports WHERE id=?", (row[0],))
    conn.commit(); conn.close()

def get_report_history():
    conn = sqlite3.connect('radar_database.db'); c = conn.cursor()
    c.execute("SELECT id, run_time, html_content FROM reports ORDER BY id DESC")
    records = c.fetchall(); conn.close(); return records

# CSS Cải tiến
st.markdown("""
<style>
    .news-card { background: #fff; padding: 18px; border-radius: 10px; margin-bottom: 15px; border-left: 5px solid #0056b3; box-shadow: 0 4px 6px rgba(0,0,0,0.05); border: 1px solid #eee; }
    .news-category { font-size: 10px; font-weight: bold; background: #212529; color: white; padding: 2px 8px; border-radius: 3px; text-transform: uppercase; }
    .news-title-link { font-size: 17px; font-weight: bold; color: #0056b3; text-decoration: none; display: block; margin-bottom: 8px; margin-top: 8px; line-height: 1.4; }
    .news-insight { font-size: 13px; font-style: italic; color: #155724; background: #d4edda; padding: 10px; border-radius: 5px; border-left: 3px solid #28a745; }
    .market-outlook { background: #111; color: #00ff41; padding: 25px; border-radius: 8px; font-family: 'Courier New', Courier, monospace; white-space: pre-wrap; line-height: 1.6; border: 1px solid #00ff41; }
    .stTabs [data-baseweb="tab-list"] { gap: 10px; }
    .stTabs [data-baseweb="tab"] { background-color: #f0f2f6; border-radius: 5px 5px 0 0; padding: 10px 20px; }
    .stTabs [aria-selected="true"] { background-color: #0056b3 !important; color: white !important; }
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
        email = st.text_input("Nhập Gmail của bạn:").lower().strip()
        if st.form_submit_button("Đăng nhập"):
            user_role = check_user_access(email)
            if user_role:
                st.session_state.logged_in = True
                st.session_state.user_email = email
                st.session_state.is_admin = (user_role == "admin")
                st.rerun()
            else: st.error("Tài khoản chưa được cấp quyền truy cập.")
    st.stop()

st.sidebar.success(f"👤 {st.session_state.user_email}")
if st.sidebar.button("Đăng xuất"):
    st.session_state.logged_in = False; st.rerun()

current_groq_key = get_api_key("GROQ")
current_gemini_key = get_api_key("GEMINI")

# Menu Admin
if st.session_state.is_admin:
    st.sidebar.markdown("---")
    st.sidebar.header("👑 Quản trị")
    with st.sidebar.expander("🔑 API Keys"):
        if current_groq_key and current_gemini_key:
            st.success("✅ Đã có Keys")
            if st.button("🔄 Reset Keys"): reset_all_api_keys(); st.rerun()
        else:
            g_key = st.text_input("Groq Key:", type="password")
            m_key = st.text_input("Gemini Key:", type="password")
            if st.button("Lưu cấu hình"):
                if g_key and m_key: add_api_key("GROQ", g_key); add_api_key("GEMINI", m_key); st.rerun()

st.sidebar.markdown("---")
st.sidebar.header("🗂️ Lịch sử")
for r_id, r_time, r_html in get_report_history():
    with st.sidebar.expander(f"🕒 {r_time}"):
        st.download_button("📥 Tải HTML", data=r_html, file_name=f"Radar_{r_id}.html", mime="text/html", key=f"dl_{r_id}")

# ==========================================
# 3. HÀM XỬ LÝ AI (Bổ sung Bất động sản)
# ==========================================
RSS_FEEDS = {
    "Mỹ 🇺🇸": ["https://rss.nytimes.com/services/xml/rss/nyt/World.xml", "http://rss.cnn.com/rss/edition_world.rss"],
    "Châu Âu 🇪🇺": ["http://feeds.bbci.co.uk/news/world/europe/rss.xml"],
    "Trung Quốc 🇨🇳": ["https://www.scmp.com/rss/318198/feed"],
    "Việt Nam 🇻🇳": ["https://vnexpress.net/rss/the-gioi.rss"]
}

def groq_analyze(api_key, raw_data, region, topics, top_n):
    client = Groq(api_key=api_key)
    prompt = f"""
    Lọc {top_n} tin từ vùng {region} về các chủ đề: {','.join(topics)}.
    ĐẶC BIỆT CHÚ TRỌNG: Các tin tức về Bất động sản, lãi suất và chính sách nhà ở.
    YÊU CẦU: DỊCH 100% SANG TIẾNG VIỆT.
    Trả về JSON: {{'data': [{{'cat':'Lĩnh vực','src':'Tên báo','tit':'Tiêu đề VN','lnk':'Link','brf':'Tóm tắt VN','ins':'Phân tích VN'}}]}}
    Dữ liệu: {json.dumps(raw_data)}
    """
    try:
        response = client.chat.completions.create(
            messages=[
                {"role": "system", "content": "You are a professional news analyst. Output ONLY JSON in Vietnamese."},
                {"role": "user", "content": prompt}
            ],
            model="llama-3.3-70b-versatile",
            temperature=0.1,
            response_format={"type": "json_object"}
        )
        return json.loads(response.choices[0].message.content).get("data", [])
    except Exception as e: return [{"cat": "Lỗi", "tit": "Lỗi Groq", "brf": str(e), "src": "Hệ thống", "lnk": "#"}]

# ==========================================
# 4. GIAO DIỆN CHÍNH
# ==========================================
st.title("🌍 Radar Chiến Lược Toàn Cầu")

regs = st.sidebar.multiselect("Vùng theo dõi:", list(RSS_FEEDS.keys()), default=["Mỹ 🇺🇸", "Việt Nam 🇻🇳"])
# Bổ sung Bất động sản vào danh mục quan tâm
topi = st.sidebar.multiselect("Lĩnh vực:", ["Kinh tế", "Bất động sản", "Chính trị", "Ngân hàng", "Công nghệ & AI"], default=["Kinh tế", "Bất động sản"])

if st.sidebar.button("🚀 CẬP NHẬT DỮ LIỆU MỚI", type="primary", use_container_width=True):
    if not current_groq_key or not current_gemini_key:
        st.error("Thiếu API Keys!")
    else:
        with st.spinner("🔄 Đang quét tin tức toàn cầu..."):
            st.session_state.news_store = {}
            for r in regs:
                raw_news = []
                for url in RSS_FEEDS[r]:
                    f = feedparser.parse(url)
                    for e in f.entries[:15]: # Tăng lượng tin thô để AI lọc tốt hơn
                        raw_news.append({"raw_title": e.get('title',''), "link": e.get('link','#'), "summary": e.get('summary','')[:300]})
                st.session_state.news_store[r] = groq_analyze(current_groq_key, raw_news, r, topi, 5)
            
            try:
                genai.configure(api_key=current_gemini_key)
                gemini = genai.GenerativeModel('gemini-2.5-flash')
                p_outlook = f"Dựa trên dữ liệu sau (chú trọng mảng Bất động sản & Kinh tế), hãy viết nhận định vĩ mô tiếng Việt sâu sắc: {json.dumps(st.session_state.news_store)}"
                st.session_state.outlook_store = gemini.generate_content(p_outlook).text
            except Exception as e: st.session_state.outlook_store = f"Lỗi Gemini: {e}"
            
            st.rerun()

# --- HIỂN THỊ THEO TAB ---
if "news_store" in st.session_state:
    # Tạo danh sách các Tab tương ứng với số nước đã chọn
    tab_titles = list(st.session_state.news_store.keys())
    if tab_titles:
        tabs = st.tabs(tab_titles)
        
        for index, region in enumerate(tab_titles):
            with tabs[index]:
                st.markdown(f"### 📍 Tin tức tại {region}")
                for i in st.session_state.news_store[region]:
                    st.markdown(f"""<div class="news-card">
                        <span class="news-category">{i.get('cat','Chung')}</span> | <b>{i.get('src','Nguồn')}</b>
                        <a class="news-title-link" href="{i.get('lnk','#')}" target="_blank">{i.get('tit','Tiêu đề')}</a>
                        <p>{i.get('brf','')}</p>
                        <div class="news-insight">💡 <b>Phân tích:</b> {i.get('ins','')}</div>
                    </div>""", unsafe_allow_html=True)
    
    st.markdown("### 📡 NHẬN ĐỊNH VĨ MÔ TỔNG HỢP (Gemini 2.5 Flash)")
    st.markdown(f'<div class="market-outlook">{st.session_state.outlook_store}</div>', unsafe_allow_html=True)
