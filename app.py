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
st.set_page_config(page_title="Radar Chiến Lược Toàn Cầu v15.0", layout="wide", page_icon="📡")

MASTER_ADMIN_EMAIL = "admin@gmail.com" # SỬA EMAIL CỦA BẠN TẠI ĐÂY

def init_db():
    conn = sqlite3.connect('radar_database.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS api_keys (id INTEGER PRIMARY KEY, platform TEXT, key_value TEXT UNIQUE)''')
    c.execute('''CREATE TABLE IF NOT EXISTS reports (id INTEGER PRIMARY KEY AUTOINCREMENT, run_time TEXT, html_content TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, email TEXT UNIQUE, role TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS user_prefs (email TEXT PRIMARY KEY, regs TEXT, topi TEXT, top_n INTEGER)''')
    
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

# --- Hàm Lưu & Tải Cài Đặt Người Dùng (Tính năng mới) ---
def save_prefs(email, regs, topi, top_n):
    conn = sqlite3.connect('radar_database.db'); c = conn.cursor()
    c.execute("REPLACE INTO user_prefs (email, regs, topi, top_n) VALUES (?, ?, ?, ?)", (email, json.dumps(regs), json.dumps(topi), top_n))
    conn.commit(); conn.close()

def load_prefs(email):
    conn = sqlite3.connect('radar_database.db'); c = conn.cursor()
    c.execute("SELECT regs, topi, top_n FROM user_prefs WHERE email=?", (email,))
    res = c.fetchone(); conn.close()
    if res: return json.loads(res[0]), json.loads(res[1]), res[2]
    return ["Việt Nam 🇻🇳", "Mỹ 🇺🇸"], ["Tài chính", "Bất động sản"], 15

# ==========================================
# GIAO DIỆN CSS (ĐÃ THU NHỎ FONT CHỮ DÀNH CHO MOBILE)
# ==========================================
st.markdown("""
<style>
    .news-card { background: #fff; padding: 15px; border-radius: 8px; margin-bottom: 12px; border-left: 4px solid #0056b3; box-shadow: 0 2px 4px rgba(0,0,0,0.05); border: 1px solid #eee; }
    .news-category { font-size: 9px; font-weight: bold; background: #212529; color: white; padding: 2px 6px; border-radius: 3px; text-transform: uppercase; }
    .news-title-link { font-size: 15px; font-weight: bold; color: #0056b3; text-decoration: none; display: block; margin: 6px 0; line-height: 1.3; }
    .news-brief { font-size: 13px; line-height: 1.4; margin-bottom: 8px; color: #333; }
    .news-insight { font-size: 11.5px; font-style: italic; color: #155724; background: #d4edda; padding: 8px; border-radius: 5px; border-left: 3px solid #28a745; line-height: 1.4; }
    .market-outlook { background: #111; color: #00ff41; padding: 15px; border-radius: 8px; font-size: 13px; font-family: 'Courier New', Courier, monospace; white-space: pre-wrap; border: 1px solid #00ff41; line-height: 1.5; }
    .stTabs [data-baseweb="tab-list"] { gap: 5px; }
    .stTabs [data-baseweb="tab"] { font-size: 14px; padding: 8px 12px; }
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

current_groq_key = get_api_key("GROQ")
current_gemini_key = get_api_key("GEMINI")

# Quản lý Sidebar (Chỉ dành cho Admin và Đăng xuất)
st.sidebar.success(f"👤 {st.session_state.user_email}")
if st.sidebar.button("Đăng xuất"): st.session_state.logged_in = False; st.rerun()

if st.session_state.is_admin:
    st.sidebar.markdown("---")
    st.sidebar.header("👑 Quản trị API")
    if st.sidebar.button("🔄 Đặt lại Keys"): reset_all_api_keys(); st.rerun()
    g_key = st.sidebar.text_input("Groq Key:", type="password")
    m_key = st.sidebar.text_input("Gemini Key:", type="password")
    if st.sidebar.button("Lưu cấu hình"): add_api_key("GROQ", g_key); add_api_key("GEMINI", m_key); st.rerun()

# ==========================================
# 3. KHO DỮ LIỆU & HÀM LỌC AI
# ==========================================
RSS_FEEDS = {
    "Việt Nam 🇻🇳": [
        "https://vnexpress.net/rss/kinh-doanh.rss", "https://vnexpress.net/rss/bat-dong-san.rss", "https://vnexpress.net/rss/the-gioi.rss",
        "https://tuoitre.vn/rss/kinh-doanh.rss", "https://tuoitre.vn/rss/tai-chinh.rss", "https://tuoitre.vn/rss/thoi-su.rss",
        "https://thanhnien.vn/rss/kinh-te.rss", "https://vietnamnet.vn/rss/kinh-doanh.rss", "https://vietnamnet.vn/rss/bat-dong-san.rss",
        "https://dantri.com.vn/rss/kinh-doanh.rss", "https://dantri.com.vn/rss/bat-dong-san.rss", "https://cafef.vn/rss/bat-dong-san.rss"
    ],
    "Mỹ 🇺🇸": [
        "https://rss.nytimes.com/services/xml/rss/nyt/Economy.xml", "https://rss.nytimes.com/services/xml/rss/nyt/RealEstate.xml", 
        "https://rss.nytimes.com/services/xml/rss/nyt/Politics.xml", "http://rss.cnn.com/rss/money_latest.rss", 
        "https://www.cnbc.com/id/10000664/device/rss", "https://www.cnbc.com/id/10000115/device/rss"
    ],
    "Trung Quốc 🇨🇳": [
        "https://www.scmp.com/rss/318198/feed", "https://www.scmp.com/rss/318200/feed",
        "https://www.scmp.com/rss/318202/feed", "http://www.xinhuanet.com/english/rss/business.xml",
        "https://www.ft.com/chinese-economy?format=rss", "https://www.ft.com/china-politics?format=rss"
    ],
    "Châu Âu 🇪🇺": [
        "http://feeds.bbci.co.uk/news/world/europe/rss.xml", "http://feeds.bbci.co.uk/news/business/rss.xml",
        "https://www.france24.com/en/business/rss", "https://www.dw.com/en/business/s-1431"
    ]
}

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
    if "scmp" in url: return "SCMP"
    if "bbc" in url: return "BBC"
    return "Báo Quốc Tế"

def groq_analyze(api_key, raw_data, region, topics, top_n):
    client = Groq(api_key=api_key)
    current_date = datetime.now().strftime("%m/%Y")
    prompt = f"""
    Tháng {current_date}. Chọn đúng {top_n} tin tại {region} từ danh sách dưới đây.
    LUẬT THÉP:
    1. ĐÚNG CHỦ ĐỀ: Lấy đúng các tin thuộc: {','.join(topics)}. Không chọn sai lĩnh vực.
    2. KHÔNG LẶP LẠI. Bỏ qua tin năm 2024.
    3. GIỮ NGUYÊN ID. 
    4. DỊCH 100% TIẾNG VIỆT.
    JSON Format: {{'data': [{{'id':'(ID)','cat':'Tên lĩnh vực','src':'Tên báo','tit':'Tiêu đề VN','brf':'Tóm tắt VN','ins':'Phân tích VN'}}]}}
    Dữ liệu: {json.dumps(raw_data, ensure_ascii=False)}
    """
    try:
        res = client.chat.completions.create(
            messages=[{"role": "system", "content": "You are a JSON API. Output in Vietnamese."}, {"role": "user", "content": prompt}],
            model="llama-3.3-70b-versatile", temperature=0.1, response_format={"type": "json_object"}
        )
        return json.loads(res.choices[0].message.content).get("data", [])
    except Exception as e: return [{"cat": "Lỗi", "tit": "Lỗi AI", "brf": str(e), "src": "Hệ thống", "lnk": "#"}]

def generate_html_report(news_data, outlook):
    now = datetime.now().strftime("%H:%M - %d/%m/%Y")
    html = f"<html><body style='font-family:sans-serif;padding:20px;font-size:14px;line-height:1.5;'><h1>Báo Cáo Radar {now}</h1>"
    html += f"<div style='background:#111;color:#0f0;padding:15px;border-radius:8px;font-size:13px;'><h3>Nhận định vĩ mô:</h3><p>{outlook.replace(chr(10), '<br>')}</p></div>"
    for reg, items in news_data.items():
        html += f"<h2>📍 {reg}</h2>"
        for i in items:
            html += f"<div style='margin-bottom:15px;border-bottom:1px solid #eee;padding-bottom:10px;'><b>[{i.get('cat')}] {i.get('src')}</b><br><a href='{i.get('lnk')}' style='font-size:15px;font-weight:bold;color:#0056b3;'>{i.get('tit')}</a><p style='font-size:13px;margin:5px 0;'>{i.get('brf')}</p><i style='font-size:12px;color:#155724;'>💡 Phân tích: {i.get('ins')}</i></div>"
    return html + "</body></html>"

# ==========================================
# 4. GIAO DIỆN CHÍNH (ĐƯA BẢNG ĐIỀU KHIỂN RA TRANG CHỦ)
# ==========================================
st.title("🌍 Radar Chiến Lược Toàn Cầu")

# Tải cài đặt cũ của người dùng
def_regs, def_topi, def_top_n = load_prefs(st.session_state.user_email)

# Khung điều khiển ngay trên giao diện Mobile
with st.expander("⚙️ BẢNG ĐIỀU KHIỂN (Bấm để mở/đóng)", expanded=True):
    regs = st.multiselect("Vùng theo dõi:", list(RSS_FEEDS.keys()), default=def_regs)
    topi = st.multiselect("Lĩnh vực:", ["Tài chính", "Bất động sản", "Kinh tế", "Chính trị", "Ngân hàng", "Công nghệ & AI"], default=def_topi)
    
    # Bắt lỗi index nếu giá trị cũ không nằm trong danh sách
    try: index_top_n = [10, 15, 20, 25].index(def_top_n)
    except ValueError: index_top_n = 1
    top_n_option = st.selectbox("Số lượng tin hiển thị mỗi vùng:", [10, 15, 20, 25], index=index_top_n)

    if st.button("🚀 CẬP NHẬT DỮ LIỆU", type="primary", use_container_width=True):
        if not current_groq_key or not current_gemini_key: st.error("Chưa có API Key!")
        else:
            # Lưu lại cấu hình cho lần sau
            save_prefs(st.session_state.user_email, regs, topi, top_n_option)
            
            with st.spinner("Đang cào dữ liệu, lọc thông minh và phân tích..."):
                st.session_state.news_store = {}; st.session_state.chat_history = []
                for r in regs:
                    raw_news = []
                    seen_links = set()
                    for url in RSS_FEEDS.get(r, []):
                        try:
                            f = feedparser.parse(url)
                            src_name = get_source_name(url)
                            for e in f.entries[:8]: 
                                title = e.get('title','')
                                link = e.get('link','#')
                                clean_summary = re.sub('<[^<]+>', '', e.get('summary','')).strip()[:100]
                                if link not in seen_links and title:
                                    seen_links.add(link)
                                    raw_news.append({"src": src_name, "tit": title, "lnk": link, "sum": clean_summary})
                        except: pass
                    
                    random.shuffle(raw_news)
                    capped_raw_news = raw_news[:40]
                    
                    ai_input = []
                    url_map = {}
                    for idx, item in enumerate(capped_raw_news):
                        str_id = str(idx)
                        url_map[str_id] = item['lnk']
                        ai_input.append({"id": str_id, "src": item['src'], "tit": item['tit'], "sum": item['sum']})
                    
                    analyzed_data = groq_analyze(current_groq_key, ai_input, r, topi, top_n_option)
                    
                    for item in analyzed_data:
                        if 'id' in item and str(item['id']) in url_map: item['lnk'] = url_map[str(item['id'])]
                        else: item['lnk'] = "#"
                    
                    st.session_state.news_store[r] = analyzed_data
                    time.sleep(3)
                
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
                        <div class="news-brief">{item.get('brf')}</div>
                        <div class="news-insight">💡 <b>Phân tích:</b> {item.get('ins')}</div>
                    </div>""", unsafe_allow_html=True)
    
    st.markdown("### 📡 NHẬN ĐỊNH VĨ MÔ")
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

# Kéo kho Lịch Sử ra ngoài màn hình chính để dễ tìm trên điện thoại
st.markdown("---")
with st.expander("🗂️ LỊCH SỬ BÁO CÁO (Click để tải)"):
    history = get_report_history()
    if not history:
        st.caption("Chưa có báo cáo nào.")
    else:
        for r_id, r_time, r_html in history:
            st.download_button(f"📥 Báo Cáo lúc {r_time}", data=r_html, file_name=f"Radar_{r_id}.html", mime="text/html", key=f"dl_main_{r_id}")
