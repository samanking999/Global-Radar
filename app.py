import streamlit as st
import feedparser
import google.generativeai as genai
from groq import Groq
import json
import sqlite3
import time
import re
import random
from datetime import datetime

# ==========================================
# 1. CẤU HÌNH GIAO DIỆN & DATABASE
# ==========================================
st.set_page_config(page_title="Radar Chiến Lược Toàn Cầu v14.2", layout="wide", page_icon="📡")

MASTER_ADMIN_EMAIL = "admin@gmail.com" # SỬA EMAIL CỦA BẠN TẠI ĐÂY

def init_db():
    conn = sqlite3.connect('radar_database.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS api_keys (id INTEGER PRIMARY KEY, platform TEXT, key_value TEXT UNIQUE)''')
    c.execute('''CREATE TABLE IF NOT EXISTS reports (id INTEGER PRIMARY KEY AUTOINCREMENT, run_time TEXT, html_content TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, email TEXT UNIQUE, role TEXT)''')
    c.execute("SELECT COUNT(*) FROM users WHERE role='admin'")
    if c.fetchone()[0] == 0:
        c.execute("INSERT OR IGNORE INTO users (email, role) VALUES (?, 'admin')", (MASTER_ADMIN_EMAIL,))
    conn.commit(); conn.close()

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
    return c.fetchall()

def check_user_access(email):
    conn = sqlite3.connect('radar_database.db'); c = conn.cursor()
    c.execute("SELECT role FROM users WHERE email=?", (email.strip().lower(),))
    res = c.fetchone(); return res[0] if res else None

def add_api_key(platform, key_value):
    conn = sqlite3.connect('radar_database.db'); c = conn.cursor()
    c.execute("DELETE FROM api_keys WHERE platform=?", (platform,))
    c.execute("INSERT INTO api_keys (platform, key_value) VALUES (?, ?)", (platform, key_value.strip()))
    conn.commit(); conn.close()

def get_api_key(platform):
    conn = sqlite3.connect('radar_database.db'); c = conn.cursor()
    c.execute("SELECT key_value FROM api_keys WHERE platform=? ORDER BY id DESC LIMIT 1", (platform,))
    res = c.fetchone(); return res[0] if res else None

def reset_all_api_keys():
    conn = sqlite3.connect('radar_database.db'); c = conn.cursor()
    c.execute("DELETE FROM api_keys"); conn.commit(); conn.close()

def save_report_to_db(html_content):
    conn = sqlite3.connect('radar_database.db'); c = conn.cursor()
    t = datetime.now().strftime("%H:%M - %d/%m/%Y")
    c.execute("INSERT INTO reports (run_time, html_content) VALUES (?, ?)", (t, html_content))
    c.execute("SELECT id FROM reports ORDER BY id DESC LIMIT -1 OFFSET 20")
    for r in c.fetchall(): c.execute("DELETE FROM reports WHERE id=?", (r[0],))
    conn.commit(); conn.close()

def get_report_history():
    conn = sqlite3.connect('radar_database.db'); c = conn.cursor()
    c.execute("SELECT id, run_time, html_content FROM reports ORDER BY id DESC")
    return c.fetchall()

# CSS
st.markdown("""
<style>
    .news-card { background: #fff; padding: 18px; border-radius: 10px; margin-bottom: 15px; border-left: 5px solid #0056b3; box-shadow: 0 4px 6px rgba(0,0,0,0.05); }
    .news-category { font-size: 10px; font-weight: bold; background: #212529; color: white; padding: 2px 8px; border-radius: 3px; text-transform: uppercase; }
    .news-title-link { font-size: 17px; font-weight: bold; color: #0056b3; text-decoration: none; display: block; margin: 8px 0; }
    .news-insight { font-size: 13px; font-style: italic; color: #155724; background: #d4edda; padding: 10px; border-radius: 5px; border-left: 3px solid #28a745; }
    .market-outlook { background: #111; color: #00ff41; padding: 25px; border-radius: 8px; font-family: monospace; white-space: pre-wrap; border: 1px solid #00ff41; }
</style>
""", unsafe_allow_html=True)

# ==========================================
# 2. HỆ THỐNG ĐĂNG NHẬP
# ==========================================
if 'logged_in' not in st.session_state: st.session_state.logged_in = False
if 'user_email' not in st.session_state: st.session_state.user_email = ""
if 'is_admin' not in st.session_state: st.session_state.is_admin = False
if 'chat_history' not in st.session_state: st.session_state.chat_history = []

if not st.session_state.logged_in:
    st.title("🔐 Đăng nhập Radar")
    with st.form("login"):
        email = st.text_input("Email:").lower().strip()
        if st.form_submit_button("Vào hệ thống"):
            role = check_user_access(email)
            if role:
                st.session_state.logged_in = True
                st.session_state.user_email = email
                st.session_state.is_admin = (role == "admin")
                st.rerun()
            else: st.error("Email không có quyền!")
    st.stop()

st.sidebar.success(f"👤 {st.session_state.user_email}")
if st.sidebar.button("Đăng xuất"): st.session_state.logged_in = False; st.rerun()

current_groq_key = get_api_key("GROQ")
current_gemini_key = get_api_key("GEMINI")

# ==========================================
# 3. MENU ĐIỀU KHIỂN & KHO DỮ LIỆU
# ==========================================
st.sidebar.markdown("---")
st.sidebar.header("⚙️ Cấu hình Radar")
regs = st.sidebar.multiselect("Vùng theo dõi:", ["Việt Nam 🇻🇳", "Mỹ 🇺🇸", "Trung Quốc 🇨🇳", "Châu Âu 🇪🇺"], default=["Việt Nam 🇻🇳", "Mỹ 🇺🇸"])
topi = st.sidebar.multiselect("Lĩnh vực:", ["Tài chính", "Bất động sản", "Kinh tế", "Chính trị", "Ngân hàng", "Công nghệ & AI"], default=["Tài chính", "Bất động sản"])
top_n_option = st.sidebar.selectbox("Số lượng tin hiển thị mỗi vùng:", [10, 15, 20, 25], index=1)

RSS_FEEDS = {
    "Việt Nam 🇻🇳": [
        "https://vnexpress.net/rss/kinh-doanh.rss", "https://vnexpress.net/rss/bat-dong-san.rss", "https://vnexpress.net/rss/the-gioi.rss",
        "https://tuoitre.vn/rss/kinh-doanh.rss", "https://tuoitre.vn/rss/tai-chinh.rss", "https://tuoitre.vn/rss/thoi-su.rss",
        "https://thanhnien.vn/rss/kinh-te.rss", "https://thanhnien.vn/rss/tai-chinh-chung-khoan.rss",
        "https://vietnamnet.vn/rss/kinh-doanh.rss", "https://vietnamnet.vn/rss/bat-dong-san.rss",
        "https://dantri.com.vn/rss/kinh-doanh.rss", "https://dantri.com.vn/rss/bat-dong-san.rss",
        "https://cafef.vn/rss/tai-chinh-ngan-hang.rss", "https://cafef.vn/rss/bat-dong-san.rss"
    ],
    "Mỹ 🇺🇸": [
        "https://rss.nytimes.com/services/xml/rss/nyt/Economy.xml", "https://rss.nytimes.com/services/xml/rss/nyt/RealEstate.xml", 
        "https://rss.nytimes.com/services/xml/rss/nyt/Politics.xml", "https://rss.nytimes.com/services/xml/rss/nyt/Technology.xml",
        "http://rss.cnn.com/rss/money_latest.rss", "http://rss.cnn.com/rss/cnn_allpolitics.rss", "http://rss.cnn.com/rss/cnn_tech.rss",
        "https://www.cnbc.com/id/10000664/device/rss", "https://www.cnbc.com/id/10000115/device/rss",
        "https://feeds.foxnews.com/foxnews/politics"
    ],
    "Trung Quốc 🇨🇳": [
        "https://www.scmp.com/rss/318198/feed", "https://www.scmp.com/rss/318200/feed",
        "https://www.scmp.com/rss/318202/feed", "https://www.scmp.com/rss/318205/feed",
        "http://www.xinhuanet.com/english/rss/china.xml", "http://www.xinhuanet.com/english/rss/business.xml",
        "https://www.ft.com/chinese-economy?format=rss", "https://www.ft.com/china-politics?format=rss"
    ],
    "Châu Âu 🇪🇺": [
        "http://feeds.bbci.co.uk/news/world/europe/rss.xml", "http://feeds.bbci.co.uk/news/business/rss.xml",
        "https://www.france24.com/en/europe/rss", "https://www.france24.com/en/business/rss",
        "https://www.dw.com/en/top-stories/europe/s-1430", "https://www.dw.com/en/business/s-1431",
        "https://www.cnbc.com/id/100004038/device/rss"
    ]
}

# Python tự động nhận diện tên báo thay vì bắt AI tự mò từ link
def get_source_name(url):
    if "vnexpress" in url: return "VnExpress"
    if "tuoitre" in url: return "Tuổi Trẻ"
    if "thanhnien" in url: return "Thanh Niên"
    if "vietnamnet" in url: return "VietnamNet"
    if "dantri" in url: return "Dân Trí"
    if "cafef" in url: return "CafeF"
    if "nytimes" in url: return "New York Times"
    if "cnn" in url: return "CNN"
    if "cnbc" in url: return "CNBC"
    if "foxnews" in url: return "Fox News"
    if "scmp" in url: return "SCMP"
    if "xinhuanet" in url: return "Xinhua"
    if "ft.com" in url: return "Financial Times"
    if "bbc" in url: return "BBC"
    if "france24" in url: return "France 24"
    if "dw.com" in url: return "DW"
    return "Báo Quốc Tế"

if st.session_state.is_admin:
    st.sidebar.markdown("---")
    st.sidebar.header("👑 Quản trị")
    with st.sidebar.expander("🔑 Cấu hình API Keys"):
        if current_groq_key and current_gemini_key:
            st.success("✅ Đã lưu API")
            if st.button("🔄 Đặt lại Keys"): reset_all_api_keys(); st.rerun()
        else:
            g_key = st.text_input("Groq Key:", type="password")
            m_key = st.text_input("Gemini Key:", type="password")
            if st.button("Lưu cấu hình"): add_api_key("GROQ", g_key); add_api_key("GEMINI", m_key); st.rerun()

# ==========================================
# 4. HÀM XỬ LÝ AI (SỬ DỤNG MẶT NẠ URL)
# ==========================================
def groq_analyze(api_key, raw_data, region, topics, top_n):
    client = Groq(api_key=api_key)
    current_date = datetime.now().strftime("%m/%Y")
    
    # Prompt yêu cầu AI nhận dữ liệu đã được gán ID và phải trả về ID tương ứng
    prompt = f"""
    Hôm nay: Tháng {current_date}.
    Chọn đúng {top_n} tin QUAN TRỌNG NHẤT tại {region} từ danh sách dưới đây.

    LUẬT THÉP:
    1. ĐÚNG CHỦ ĐỀ: CHỈ được lấy các tin thuộc các nhóm này: {','.join(topics)}. KHÔNG chọn sai lĩnh vực.
    2. KHÔNG LẶP LẠI. Bỏ qua tin cũ năm 2024.
    3. GIỮ NGUYÊN ID: Bạn PHẢI trả về chính xác chuỗi 'id' của bài báo bạn chọn.
    4. DỊCH 100% TIẾNG VIỆT. Tóm tắt và đưa ra phân tích sâu sắc.
    
    JSON Format: {{'data': [{{'id':'(ID tương ứng)','cat':'Tên lĩnh vực','src':'Tên báo','tit':'Tiêu đề VN','brf':'Tóm tắt VN','ins':'Phân tích VN'}}]}}
    Dữ liệu: {json.dumps(raw_data, ensure_ascii=False)}
    """
    try:
        res = client.chat.completions.create(
            messages=[{"role": "system", "content": "You are a JSON API. Strictly enforce rules and keep IDs intact. Output in Vietnamese."}, {"role": "user", "content": prompt}],
            model="llama-3.3-70b-versatile", temperature=0.1, response_format={"type": "json_object"}
        )
        return json.loads(res.choices[0].message.content).get("data", [])
    except Exception as e: return [{"cat": "Lỗi", "tit": "Lỗi AI/Quá tải", "brf": str(e), "src": "Hệ thống", "lnk": "#"}]

def generate_html_report(news_data, outlook):
    now = datetime.now().strftime("%H:%M - %d/%m/%Y")
    html = f"<html><body style='font-family:sans-serif;padding:30px'><h1>Báo Cáo Radar {now}</h1>"
    html += f"<div style='background:#111;color:#0f0;padding:25px'><h3>Nhận định vĩ mô:</h3><p>{outlook.replace(chr(10), '<br>')}</p></div>"
    for reg, items in news_data.items():
        html += f"<h2>📍 {reg}</h2>"
        for i in items:
            html += f"<div style='margin-bottom:15px'><b>[{i.get('cat')}] {i.get('src')}</b><br><a href='{i.get('lnk')}'><b>{i.get('tit')}</b></a><p>{i.get('brf')}</p></div>"
    return html + "</body></html>"

# ==========================================
# 5. LUỒNG CHẠY CHÍNH (URL MASKING)
# ==========================================
st.title("🌍 Radar Chiến Lược Toàn Cầu")

if st.sidebar.button("🚀 CẬP NHẬT DỮ LIỆU", type="primary", use_container_width=True):
    if not current_groq_key or not current_gemini_key: st.error("Chưa có API Key!")
    else:
        with st.spinner("Đang cào dữ liệu, nén Token và phân tích..."):
            st.session_state.news_store = {}; st.session_state.chat_history = []
            
            for r in regs:
                raw_news = []
                seen_links = set()
                
                # Quét tin từ kho
                for url in RSS_FEEDS.get(r, []):
                    try:
                        f = feedparser.parse(url)
                        src_name = get_source_name(url)
                        for e in f.entries[:8]: 
                            title = e.get('title','')
                            link = e.get('link','#')
                            clean_summary = re.sub('<[^<]+>', '', e.get('summary','')).strip()[:100] # Nén tóm tắt xuống 100 chữ
                            
                            if link not in seen_links and title:
                                seen_links.add(link)
                                raw_news.append({"src": src_name, "tit": title, "lnk": link, "sum": clean_summary})
                    except: pass
                
                random.shuffle(raw_news)
                # Lấy ngẫu nhiên 35-40 tin (Vừa đủ chọn lọc 25 tin, vừa không lố Token)
                capped_raw_news = raw_news[:40]
                
                # KỸ THUẬT MASKING: Tạo bộ từ điển chứa Link, chỉ đưa ID cho AI
                ai_input = []
                url_map = {}
                for idx, item in enumerate(capped_raw_news):
                    str_id = str(idx)
                    url_map[str_id] = item['lnk'] # Giữ lại Link ở Python
                    ai_input.append({
                        "id": str_id,
                        "src": item['src'],
                        "tit": item['tit'],
                        "sum": item['sum']
                    }) # Chỉ gửi cục này đi
                
                # Gọi AI xử lý
                analyzed_data = groq_analyze(current_groq_key, ai_input, r, topi, top_n_option)
                
                # UNMASK: Lắp lại Link vào dữ liệu sau khi AI trả về
                for item in analyzed_data:
                    if 'id' in item and str(item['id']) in url_map:
                        item['lnk'] = url_map[str(item['id'])]
                    else:
                        item['lnk'] = "#"
                
                st.session_state.news_store[r] = analyzed_data
                time.sleep(3) # Nghỉ 3s bảo vệ máy chủ
            
            try:
                genai.configure(api_key=current_gemini_key)
                gemini = genai.GenerativeModel('gemini-2.5-flash')
                st.session_state.outlook_store = gemini.generate_content(f"Nhận định vĩ mô chuyên sâu. Tập trung vào {','.join(topi)}: {json.dumps(st.session_state.news_store)}").text
            except Exception as e: st.session_state.outlook_store = f"Lỗi Gemini: {e}"
            
            save_report_to_db(generate_html_report(st.session_state.news_store, st.session_state.outlook_store))
            st.rerun()

# --- HIỂN THỊ DỮ LIỆU ---
if "news_store" in st.session_state:
    tab_list = list(st.session_state.news_store.keys())
    if tab_list:
        tabs = st.tabs(tab_list)
        for idx, region in enumerate(tab_list):
            with tabs[idx]:
                for item in st.session_state.news_store[region]:
                    st.markdown(f"""<div class="news-card">
                        <span class="news-category">{item.get('cat')}</span> | <b>{item.get('src')}</b>
                        <a class="news-title-link" href="{item.get('lnk')}" target="_blank">{item.get('tit')}</a>
                        <p>{item.get('brf')}</p>
                        <div class="news-insight">💡 <b>Phân tích:</b> {item.get('ins')}</div>
                    </div>""", unsafe_allow_html=True)
    
    st.markdown("### 📡 NHẬN ĐỊNH VĨ MÔ TỔNG HỢP (Gemini 2.5 Flash)")
    st.markdown(f'<div class="market-outlook">{st.session_state.outlook_store}</div>', unsafe_allow_html=True)
    
    st.markdown("---")
    st.subheader("💬 Trợ lý Chiến lược")
    for msg in st.session_state.chat_history:
        with st.chat_message(msg["role"]): st.write(msg["content"])
        
    if chat_input := st.chat_input("Hỏi trợ lý về dữ liệu..."):
        st.session_state.chat_history.append({"role": "user", "content": chat_input})
        with st.chat_message("user"): st.write(chat_input)
        with st.chat_message("assistant"):
            try:
                genai.configure(api_key=current_gemini_key)
                res = genai.GenerativeModel('gemini-2.5-flash').generate_content(f"Dữ liệu: {json.dumps(st.session_state.news_store)}\nHỏi: {chat_input}")
                st.write(res.text)
                st.session_state.chat_history.append({"role": "assistant", "content": res.text})
            except Exception as e: st.error(f"Lỗi: {e}")
