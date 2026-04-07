import streamlit as st
import feedparser
import google.generativeai as genai
from groq import Groq
import json
import sqlite3
from datetime import datetime
import re

# ==========================================
# 1. CẤU HÌNH GIAO DIỆN & DATABASE
# ==========================================
st.set_page_config(page_title="Radar Chiến Lược Toàn Cầu v12.2", layout="wide", page_icon="📡")

# !!! QUAN TRỌNG: SỬA EMAIL NÀY THÀNH EMAIL CỦA BẠN !!!
MASTER_ADMIN_EMAIL = "admin@gmail.com"

def init_db():
    conn = sqlite3.connect('radar_database.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS api_keys (id INTEGER PRIMARY KEY, platform TEXT, key_value TEXT UNIQUE)''')
    c.execute('''CREATE TABLE IF NOT EXISTS reports (id INTEGER PRIMARY KEY AUTOINCREMENT, run_time TEXT, html_content TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, email TEXT UNIQUE, role TEXT)''')
    
    # Khởi tạo Master Admin mặc định
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
    c.execute("SELECT id FROM reports ORDER BY id DESC OFFSET 20")
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
    .news-category { font-size: 10px; font-weight: bold; background: #212529; color: white; padding: 2px 8px; border-radius: 3px; }
    .news-title-link { font-size: 17px; font-weight: bold; color: #0056b3; text-decoration: none; display: block; margin-bottom: 8px; margin-top: 8px; }
    .news-insight { font-size: 13px; font-style: italic; color: #155724; background: #d4edda; padding: 10px; border-radius: 5px; }
    .market-outlook { background: #111; color: #00ff41; padding: 20px; border-radius: 8px; font-family: monospace; }
</style>
""", unsafe_allow_html=True)

# ==========================================
# 2. HỆ THỐNG ĐĂNG NHẬP
# ==========================================
if 'logged_in' not in st.session_state: st.session_state.logged_in = False
if 'user_email' not in st.session_state: st.session_state.user_email = ""
if 'is_admin' not in st.session_state: st.session_state.is_admin = False

def login_screen():
    st.title("🔐 Cổng Đăng Nhập Radar")
    with st.form("login_form"):
        email = st.text_input("Nhập Gmail của bạn:")
        submit = st.form_submit_button("Đăng nhập")
        if submit:
            user_role = check_user_access(email)
            if user_role:
                st.session_state.logged_in = True
                st.session_state.user_email = email
                st.session_state.is_admin = (user_role == "admin")
                st.rerun()
            else:
                st.error("Tài khoản chưa được cấp quyền. Vui lòng liên hệ Admin.")
    st.stop()

if not st.session_state.logged_in: login_screen()

st.sidebar.success(f"👤 {st.session_state.user_email}")

# ĐÃ SỬA LỖI SIZE="SMALL" Ở ĐÂY
if st.sidebar.button("Đăng xuất"):
    st.session_state.logged_in = False; st.rerun()

current_groq_key = get_api_key("GROQ")
current_gemini_key = get_api_key("GEMINI")

# ==========================================
# 3. MENU ADMIN
# ==========================================
if st.session_state.is_admin:
    st.sidebar.markdown("---")
    st.sidebar.header("👑 Khu vực Admin")
    
    with st.sidebar.expander("👥 Quản lý Truy cập"):
        new_email = st.text_input("Mời người mới (Email):")
        new_role = st.selectbox("Cấp quyền:", ["user", "admin"])
        if st.button("Thêm User"):
            if add_user(new_email, new_role): st.success("Đã thêm!"); st.rerun()
            else: st.warning("Email đã tồn tại.")
        st.write("📋 **Danh sách:**")
        for u_email, u_role in get_all_users(): st.caption(f"- {u_email} ({u_role})")
    
    with st.sidebar.expander("🔑 Quản lý API Keys", expanded=(not current_groq_key or not current_gemini_key)):
        if current_groq_key and current_gemini_key:
            st.success("✅ Đã kết nối API an toàn.")
            st.caption(f"Groq: ...{current_groq_key[-4:]} | Gemini: ...{current_gemini_key[-4:]}")
            if st.button("🔄 Thay đổi API Keys", type="secondary"):
                reset_all_api_keys()
                st.rerun()
        else:
            st.warning("⚠️ Hệ thống chưa có API Key.")
            new_groq = st.text_input("Nhập Groq API Key:", type="password")
            new_gemini = st.text_input("Nhập Gemini API Key:", type="password")
            if st.button("Lưu API Keys", type="primary"):
                if new_groq and new_gemini:
                    add_api_key("GROQ", new_groq)
                    add_api_key("GEMINI", new_gemini)
                    st.rerun()
                else:
                    st.error("Nhập đủ cả 2 Key!")

st.sidebar.markdown("---")
st.sidebar.header("🗂️ Lịch sử Báo cáo")
history_records = get_report_history()
if not history_records: st.sidebar.caption("Chưa có dữ liệu.")
else:
    for rep_id, rep_time, html_data in history_records:
        with st.sidebar.expander(f"🕒 {rep_time}"):
            st.download_button("📥 Tải File HTML", data=html_data, file_name=f"Radar_{rep_id}.html", mime="text/html", key=f"dl_{rep_id}", use_container_width=True)

# ==========================================
# 4. HÀM XỬ LÝ LÕI
# ==========================================
RSS_FEEDS = {
    "Mỹ 🇺🇸": ["https://rss.nytimes.com/services/xml/rss/nyt/World.xml"],
    "Châu Âu 🇪🇺": ["http://feeds.bbci.co.uk/news/world/europe/rss.xml"],
    "Trung Quốc 🇨🇳": ["https://www.scmp.com/rss/318198/feed"],
    "Việt Nam 🇻🇳": ["https://vnexpress.net/rss/the-gioi.rss"]
}
CATEGORIES = ["Kinh tế", "Chính trị", "Ngân hàng", "Công nghệ & AI"]
SAFE_SETTINGS = [{"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"}, {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"}, {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"}, {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"}]

def fetch_latest_news(urls):
    res = []
    for u in urls:
        try:
            # ĐÃ GIẢM TẢI: Chỉ lấy 10 tin mới nhất để tiết kiệm Token Groq
            for entry in feedparser.parse(u).entries[:10]: 
                res.append({"raw_title": entry.get('title',''), "link": entry.get('link','#'), "summary": entry.get('summary','')[:200]})
        except: pass
    return res

def groq_analyze(api_key, raw_data, region, topics, top_n):
    client = Groq(api_key=api_key)
    prompt = f"Lọc {top_n} tin ở {region} về {','.join(topics)}. Tóm tắt 2 dòng. Trả về JSON: {{'data': [{{'cat':'','src':'','tit':'','lnk':'','brf':'','ins':''}}]}}. Data: {json.dumps(raw_data)}"
    try:
        response = client.chat.completions.create(
            messages=[{"role": "system", "content": "You are a JSON API. Output strictly a JSON object."}, {"role": "user", "content": prompt}], 
            model="llama-3.1-8b-instant", # ĐÃ ĐỔI SANG ĐỘNG CƠ TIẾT KIỆM (8B)
            temperature=0.1, 
            response_format={"type": "json_object"}
        )
        return json.loads(response.choices[0].message.content).get("data", [])
    except Exception as e: return [{"cat": "Lỗi", "tit": "Lỗi lấy tin", "brf": str(e)}]

def generate_html_report(news_data, outlook):
    now_str = datetime.now().strftime("%H:%M - %d/%m/%Y")
    html = f"<html><head><meta charset='utf-8'><title>Radar - {now_str}</title><style>body{{font-family:Arial;max-width:1000px;margin:auto;padding:20px}} h1{{color:#0056b3}} .card{{background:#f9f9f9;padding:15px;margin-bottom:15px;border-left:4px solid #0056b3}}</style></head><body>"
    html += f"<h1>🌍 Báo Cáo Radar ({now_str})</h1><h2>👁️ Vĩ Mô</h2><div style='background:#111;color:#0f0;padding:15px'>{outlook.replace(chr(10), '<br>')}</div>"
    for region, items in news_data.items():
        html += f"<h2 style='color:#d9534f;margin-top:30px'>📍 {region}</h2>"
        for item in items:
            if isinstance(item, dict):
                html += f"<div class='card'><b>[{item.get('cat','')}] {item.get('src','')}</b><br><a href='{item.get('lnk','#')}'><b>{item.get('tit','')}</b></a><p>{item.get('brf','')}</p><i>💡 {item.get('ins','')}</i></div>"
    return html + "</body></html>"

# ==========================================
# 5. ĐIỀU KHIỂN RADAR
# ==========================================
st.title("🌍 Radar Chiến Lược Toàn Cầu")

st.sidebar.markdown("---")
st.sidebar.header("⚙️ Chạy Radar")
selected_regions = st.sidebar.multiselect("Vùng:", list(RSS_FEEDS.keys()), default=list(RSS_FEEDS.keys())[:2])
selected_topics = st.sidebar.multiselect("Lĩnh vực:", CATEGORIES, default=["Kinh tế", "Chính trị"])
top_n_option = st.sidebar.radio("Số tin mỗi vùng:", [5, 10], horizontal=True)

if st.sidebar.button("🚀 CẬP NHẬT DỮ LIỆU MỚI", type="primary", use_container_width=True):
    if not current_groq_key or not current_gemini_key: 
        st.error("Hệ thống chưa có API Key! Vui lòng nhờ Admin nhập ở thanh bên trái.")
    elif not selected_regions or not selected_topics: 
        st.warning("Chọn ít nhất 1 vùng và 1 lĩnh vực!")
    else:
        with st.spinner("🔄 Hệ thống Lai đang vận hành..."):
            st.session_state.news_store = {}; st.session_state.chat_history = []
            
            for region in selected_regions:
                raw = fetch_latest_news(RSS_FEEDS[region])
                if raw: st.session_state.news_store[region] = groq_analyze(current_groq_key, raw, region, selected_topics, top_n_option)
            
            try:
                genai.configure(api_key=current_gemini_key)
                st.session_state.outlook_store = genai.GenerativeModel('gemini-2.5-flash').generate_content(f"Nhận định vĩ mô từ tin tức sau: {json.dumps(st.session_state.news_store)}", safety_settings=SAFE_SETTINGS).text
            except Exception as e: st.session_state.outlook_store = f"Lỗi Gemini: {e}"
            
            save_report_to_db(generate_html_report(st.session_state.news_store, st.session_state.outlook_store))
            st.toast("✅ Đã lưu báo cáo vào lịch sử!", icon="💾")

if "news_store" in st.session_state and st.session_state.news_store:
    tabs = st.tabs(list(st.session_state.news_store.keys()))
    for i, region in enumerate(st.session_state.news_store.keys()):
        with tabs[i]:
            for item in st.session_state.news_store[region]:
                if isinstance(item, dict):
                    st.markdown(f"""
                    <div class="news-card">
                        <span class="news-category">{item.get('cat', 'Chung')}</span> <b>{item.get('src', 'Nguồn')}</b>
                        <a href="{item.get('lnk', '#')}" target="_blank" class="news-title-link">{item.get('tit', 'Tiêu đề')} 🔗</a>
                        <div class="news-brief">{item.get('brf', '')}</div>
                        <div class="news-insight">💡 <b>Phân tích:</b> {item.get('ins', '')}</div>
                    </div>""", unsafe_allow_html=True)
    
    st.markdown("### 📡 NHẬN ĐỊNH VĨ MÔ")
    st.markdown(f'<div class="market-outlook">{st.session_state.outlook_store}</div>', unsafe_allow_html=True)

    st.markdown("---")
    st.subheader("💬 Trợ lý Gemini Chuyên Sâu")
    for msg in st.session_state.chat_history:
        with st.chat_message(msg["role"]): st.write(msg["content"])
        
    if chat_input := st.chat_input("Hỏi trợ lý về dữ liệu vừa quét..."):
        st.session_state.chat_history.append({"role": "user", "content": chat_input})
        with st.chat_message("user"): st.write(chat_input)
        with st.chat_message("assistant"):
            try:
                genai.configure(api_key=current_gemini_key)
                res = genai.GenerativeModel('gemini-2.5-flash').generate_content(f"Dữ liệu: {json.dumps(st.session_state.news_store)}\nHỏi: {chat_input}", safety_settings=SAFE_SETTINGS)
                st.write(res.text)
                st.session_state.chat_history.append({"role": "assistant", "content": res.text})
            except Exception as e: st.error(f"Lỗi: {e}")
