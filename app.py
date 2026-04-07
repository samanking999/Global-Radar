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
st.set_page_config(page_title="Radar Chiến Lược Toàn Cầu v13.0", layout="wide", page_icon="📡")

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

# --- Các hàm Database ---
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

# CSS
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
# 2. HỆ THỐNG ĐĂNG NHẬP & BỘ NHỚ
# ==========================================
if 'logged_in' not in st.session_state: st.session_state.logged_in = False
if 'user_email' not in st.session_state: st.session_state.user_email = ""
if 'is_admin' not in st.session_state: st.session_state.is_admin = False
if 'chat_history' not in st.session_state: st.session_state.chat_history = []

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

# ==========================================
# 3. MENU ĐIỀU KHIỂN & CÀI ĐẶT
# ==========================================
# Menu cấu hình Radar
st.sidebar.markdown("---")
st.sidebar.header("⚙️ Cấu hình Radar")
regs = st.sidebar.multiselect("Vùng theo dõi:", ["Việt Nam 🇻🇳", "Mỹ 🇺🇸", "Trung Quốc 🇨🇳", "Châu Âu 🇪🇺"], default=["Việt Nam 🇻🇳", "Mỹ 🇺🇸"])
topi = st.sidebar.multiselect("Lĩnh vực:", ["Bất động sản", "Kinh tế", "Chính trị", "Ngân hàng", "Công nghệ & AI"], default=["Bất động sản", "Kinh tế"])

# KHÔI PHỤC MENU SỐ LƯỢNG TIN
top_n_option = st.sidebar.selectbox("Số lượng tin hiển thị mỗi vùng:", [5, 10, 15, 20], index=0)

# Menu Admin
if st.session_state.is_admin:
    st.sidebar.markdown("---")
    st.sidebar.header("👑 Quản trị hệ thống")
    with st.sidebar.expander("🔑 Cấu hình API Keys"):
        if current_groq_key and current_gemini_key:
            st.success("✅ API Keys đã thiết lập")
            if st.button("🔄 Đặt lại Keys"): reset_all_api_keys(); st.rerun()
        else:
            g_key = st.text_input("Groq API Key:", type="password")
            m_key = st.text_input("Gemini API Key:", type="password")
            if st.button("Lưu cấu hình"):
                if g_key and m_key: add_api_key("GROQ", g_key); add_api_key("GEMINI", m_key); st.rerun()

    with st.sidebar.expander("👥 Quản lý Người dùng"):
        new_u = st.text_input("Email người mới:").lower().strip()
        role_u = st.selectbox("Quyền hạn:", ["user", "admin"])
        if st.button("Thêm User"):
            if add_user(new_u, role_u): st.success("Đã thêm!"); st.rerun()

st.sidebar.markdown("---")
st.sidebar.header("🗂️ Lịch sử Báo cáo")
for r_id, r_time, r_html in get_report_history():
    with st.sidebar.expander(f"🕒 {r_time}"):
        st.download_button("📥 Tải Báo Cáo", data=r_html, file_name=f"Radar_{r_id}.html", mime="text/html", key=f"dl_{r_id}")

# ==========================================
# 4. HÀM XỬ LÝ AI & TIN TỨC
# ==========================================
# Tăng cường Nguồn RSS BĐS
RSS_FEEDS = {
    "Việt Nam 🇻🇳": ["https://vnexpress.net/rss/bat-dong-san.rss", "https://vnexpress.net/rss/kinh-doanh.rss", "https://tuoitre.vn/rss/kinh-doanh.rss"],
    "Mỹ 🇺🇸": ["https://rss.nytimes.com/services/xml/rss/nyt/RealEstate.xml", "https://rss.nytimes.com/services/xml/rss/nyt/Economy.xml"],
    "Trung Quốc 🇨🇳": ["https://www.scmp.com/rss/318198/feed"],
    "Châu Âu 🇪🇺": ["http://feeds.bbci.co.uk/news/world/europe/rss.xml"]
}

def groq_analyze(api_key, raw_data, region, topics, top_n):
    client = Groq(api_key=api_key)
    current_date = datetime.now().strftime("%m/%Y")
    
    # ÉP BỘ LỌC THỜI GIAN THỰC ĐỂ CHỐNG TIN CŨ
    prompt = f"""
    Hệ thống đang chạy vào thời điểm: Tháng {current_date}.
    Từ danh sách tin thô bên dưới, hãy lọc ra {top_n} tin MỚI NHẤT và QUAN TRỌNG NHẤT tại {region} về: {','.join(topics)}.
    
    QUY TẮC TỐI THƯỢNG:
    1. TUYỆT ĐỐI KHÔNG lấy các bài báo có nội dung/tiêu đề nhắc đến các năm cũ (2024 trở về trước).
    2. Tập trung cao độ vào các tin tức Bất động sản, thị trường nhà đất mới nhất.
    3. DỊCH 100% SANG TIẾNG VIỆT.
    
    Trả về JSON: {{'data': [{{'cat':'Lĩnh vực','src':'Tên báo','tit':'Tiêu đề tiếng Việt','lnk':'Link','brf':'Tóm tắt VN','ins':'Phân tích VN'}}]}}
    Dữ liệu nguồn: {json.dumps(raw_data)}
    """
    try:
        response = client.chat.completions.create(
            messages=[
                {"role": "system", "content": "You are a top-tier news analyst. You only output valid JSON. You strictly filter out old news (pre-2025). All output in Vietnamese."},
                {"role": "user", "content": prompt}
            ],
            model="llama-3.3-70b-versatile",
            temperature=0.1,
            response_format={"type": "json_object"}
        )
        return json.loads(response.choices[0].message.content).get("data", [])
    except Exception as e: return [{"cat": "Lỗi", "tit": "Lỗi phân tích Groq", "brf": str(e), "src": "Hệ thống", "lnk": "#"}]

def generate_html_report(news_data, outlook):
    now = datetime.now().strftime("%H:%M - %d/%m/%Y")
    html = f"<html><body style='font-family:sans-serif;padding:30px;line-height:1.6;'><h1>Báo Cáo Radar Chiến Lược {now}</h1>"
    html += f"<div style='background:#111;color:#0f0;padding:25px;border-radius:10px;'><h3>📊 Nhận định vĩ mô:</h3><p>{outlook.replace(chr(10), '<br>')}</p></div>"
    for reg, items in news_data.items():
        html += f"<h2 style='border-bottom:2px solid #0056b3;padding-top:20px;'>📍 {reg}</h2>"
        for i in items:
            html += f"<div style='margin-bottom:20px;border-bottom:1px solid #eee;padding-bottom:10px;'><b>[{i.get('cat','Chung')}] {i.get('src','Nguồn')}</b><br><a href='{i.get('lnk','#')}'><b>{i.get('tit','Tiêu đề')}</b></a><p>{i.get('brf','')}</p><i>💡 Phân tích: {i.get('ins','')}</i></div>"
    return html + "</body></html>"

# ==========================================
# 5. LUỒNG CHẠY & GIAO DIỆN CHÍNH
# ==========================================
st.title("🌍 Radar Chiến Lược Toàn Cầu")

if st.sidebar.button("🚀 CẬP NHẬT DỮ LIỆU MỚI", type="primary", use_container_width=True):
    if not current_groq_key or not current_gemini_key:
        st.error("Vui lòng cấu hình API Key trong mục Admin Control.")
    else:
        with st.spinner("🔄 Đang rà quét tin tức mới nhất..."):
            st.session_state.news_store = {}
            st.session_state.chat_history = []
            
            # Quét tin với Groq
            for r in regs:
                raw_news = []
                for url in RSS_FEEDS.get(r, []):
                    f = feedparser.parse(url)
                    for e in f.entries[:20]: # Lấy mẫu 20 tin để Groq có dữ liệu lọc bỏ tin cũ
                        raw_news.append({
                            "raw_title": e.get('title',''), 
                            "link": e.get('link','#'), 
                            "summary": e.get('summary','')[:300]
                        })
                st.session_state.news_store[r] = groq_analyze(current_groq_key, raw_news, r, topi, top_n_option)
            
            # Nhận định bằng Gemini 2.5 Flash
            try:
                genai.configure(api_key=current_gemini_key)
                gemini = genai.GenerativeModel('gemini-2.5-flash')
                p_outlook = f"""
                Dựa trên dữ liệu tin tức dưới đây, hãy viết một bản NHẬN ĐỊNH VĨ MÔ chuyên sâu bằng tiếng Việt.
                Đặc biệt chú ý đến xu hướng Bất động sản và Kinh tế. Trình bày chuyên nghiệp.
                Dữ liệu: {json.dumps(st.session_state.news_store)}
                """
                st.session_state.outlook_store = gemini.generate_content(p_outlook).text
            except Exception as e:
                st.session_state.outlook_store = f"Lỗi Gemini 2.5 Flash: {str(e)}"
            
            # Lưu báo cáo
            save_report_to_db(generate_html_report(st.session_state.news_store, st.session_state.outlook_store))
            st.rerun()

# Hiển thị dữ liệu (Dạng Tab)
if "news_store" in st.session_state:
    tab_titles = list(st.session_state.news_store.keys())
    if tab_titles:
        tabs = st.tabs(tab_titles)
        for index, region in enumerate(tab_titles):
            with tabs[index]:
                st.markdown(f"### 📍 Điểm tin: {region}")
                for i in st.session_state.news_store[region]:
                    st.markdown(f"""<div class="news-card">
                        <span class="news-category">{i.get('cat','Chung')}</span> | <b>{i.get('src','Nguồn')}</b>
                        <a class="news-title-link" href="{i.get('lnk','#')}" target="_blank">{i.get('tit','Tiêu đề')}</a>
                        <p>{i.get('brf','')}</p>
                        <div class="news-insight">💡 <b>Phân tích:</b> {i.get('ins','')}</div>
                    </div>""", unsafe_allow_html=True)
    
    st.markdown("### 📡 NHẬN ĐỊNH VĨ MÔ TỔNG HỢP (Gemini 2.5 Flash)")
    st.markdown(f'<div class="market-outlook">{st.session_state.outlook_store}</div>', unsafe_allow_html=True)

    # KHUNG CHAT ASSISTANT
    st.markdown("---")
    st.subheader("💬 Trợ lý Chiến lược")
    for msg in st.session_state.chat_history:
        with st.chat_message(msg["role"]): st.write(msg["content"])
        
    if chat_input := st.chat_input("VD: Tình hình bất động sản Việt Nam hôm nay thế nào?"):
        st.session_state.chat_history.append({"role": "user", "content": chat_input})
        with st.chat_message("user"): st.write(chat_input)
        with st.chat_message("assistant"):
            try:
                genai.configure(api_key=current_gemini_key)
                res = genai.GenerativeModel('gemini-2.5-flash').generate_content(
                    f"Dữ liệu bản tin hôm nay: {json.dumps(st.session_state.news_store)}\n\nHỏi: {chat_input}"
                )
                st.write(res.text)
                st.session_state.chat_history.append({"role": "assistant", "content": res.text})
            except Exception as e: st.error(f"Lỗi hệ thống Chat: {e}")
