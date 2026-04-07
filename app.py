import streamlit as st
import feedparser
import google.generativeai as genai
from groq import Groq
import json
import time 
from datetime import datetime
import re # Thư viện bóc tách dữ liệu chống lỗi JSON

# ==========================================
# 1. CẤU HÌNH GIAO DIỆN & CSS
# ==========================================
st.set_page_config(page_title="Radar Chiến Lược Toàn Cầu v9.2", layout="wide", page_icon="📡")

st.markdown("""
<style>
    .news-card { background-color: #ffffff; padding: 18px; border-radius: 10px; margin-bottom: 15px; border-left: 5px solid #0056b3; box-shadow: 0 4px 6px rgba(0,0,0,0.05); border: 1px solid #eee; }
    .news-header { display: flex; justify-content: space-between; margin-bottom: 10px; }
    .news-category { font-size: 10px; font-weight: bold; background-color: #212529; color: white; padding: 2px 8px; border-radius: 3px; text-transform: uppercase; }
    .news-title-link { font-size: 17px; font-weight: 800; color: #0056b3; text-decoration: none; line-height: 1.3; display: block; margin-bottom: 8px; }
    .news-title-link:hover { color: #d9534f; text-decoration: underline; }
    .news-brief { font-size: 14px; color: #333; line-height: 1.6; margin-bottom: 12px; }
    .news-insight { font-size: 13px; font-style: italic; color: #155724; background-color: #d4edda; padding: 10px; border-radius: 5px; border-left: 3px solid #28a745; }
    .market-outlook { background-color: #111; color: #00ff41; padding: 20px; border-radius: 8px; font-family: 'Courier New', Courier, monospace; font-size: 14px; border: 1px solid #00ff41; margin-bottom: 20px;}
    .chat-container { margin-top: 40px; padding-top: 20px; border-top: 2px solid #eee; }
</style>
""", unsafe_allow_html=True)

# ==========================================
# 2. KHỞI TẠO BỘ NHỚ (SESSION STATE)
# ==========================================
if "news_store" not in st.session_state: st.session_state.news_store = {}
if "outlook_store" not in st.session_state: st.session_state.outlook_store = ""
if "chat_history" not in st.session_state: st.session_state.chat_history = []

# ==========================================
# 3. NGUỒN TIN TỨC & BỘ LỌC
# ==========================================
RSS_FEEDS = {
    "Mỹ 🇺🇸": ["https://rss.nytimes.com/services/xml/rss/nyt/World.xml", "http://rss.cnn.com/rss/edition_world.rss"],
    "Châu Âu 🇪🇺": ["http://feeds.bbci.co.uk/news/world/europe/rss.xml", "https://www.france24.com/en/europe/rss"],
    "Nga 🇷🇺": ["https://www.themoscowtimes.com/rss/news", "https://tass.com/rss/v2.xml"],
    "Trung Quốc 🇨🇳": ["https://www.scmp.com/rss/318198/feed", "http://www.xinhuanet.com/english/rss/worldrss.xml"],
    "Việt Nam 🇻🇳": ["https://vnexpress.net/rss/the-gioi.rss", "https://tuoitre.vn/rss/the-gioi.rss"]
}
CATEGORIES = ["Kinh tế", "Chính trị", "Ngân hàng", "Công nghệ & AI", "Quân sự", "Năng lượng"]

SAFE_SETTINGS = [
    {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"}
]

# ==========================================
# 4. HÀM XỬ LÝ DỮ LIỆU & KIẾN TRÚC LAI
# ==========================================
def fetch_latest_news(urls, max_items_per_url=20):
    results = []
    for url in urls:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:max_items_per_url]:
                results.append({"raw_title": entry.get('title', ''), "link": entry.get('link', '#'), "summary": entry.get('summary', '')[:200]})
        except: continue
    return results

def groq_analyze_worker(groq_key, raw_data, region, topic_list, top_n):
    """CÔNG NHÂN: Dùng Groq (Llama 3.3) tóm tắt & Kẹp Regex gắp JSON chống lỗi"""
    client = Groq(api_key=groq_key)
    prompt = f"""
    Khu vực: {region}.
    Từ danh sách tin mới nhất:
    1. Lọc ra ĐÚNG {top_n} tin quan trọng nhất thuộc: {", ".join(topic_list)}.
    2. Tóm tắt 2-3 DÒNG cho mỗi tin.
    3. BẮT BUỘC trả về ĐÚNG 1 mảng JSON, không giải thích.
    Cấu trúc chuẩn:
    [
      {{"cat": "Lĩnh vực", "src": "Tên báo", "tit": "Tiêu đề tiếng Việt", "lnk": "Link gốc", "brf": "Tóm tắt 2-3 dòng", "ins": "Nhận định 1 câu"}}
    ]
    Dữ liệu thô: {json.dumps(raw_data)}
    """
    try:
        response = client.chat.completions.create(
            messages=[
                {"role": "system", "content": "You are a data API. Output ONLY a valid JSON array. Do not include markdown formatting. Do not add conversational text."},
                {"role": "user", "content": prompt}
            ],
            model="llama-3.3-70b-versatile",
            temperature=0.1 # Hạ nhiệt độ để AI trả lời nguyên tắc hơn
        )
        
        raw_text = response.choices[0].message.content.strip()
        
        # BỘ LỌC REGEX: TÌM VÀ GẮP CHÍNH XÁC MẢNG JSON
        match = re.search(r'\[.*\]', raw_text, re.DOTALL)
        if match:
            clean_json = match.group(0)
        else:
            clean_json = raw_text
            
        return json.loads(clean_json)
        
    except Exception as e: 
        error_msg = raw_text if 'raw_text' in locals() else "Không phản hồi"
        return [{"cat": "Lỗi", "src": "Hệ thống", "tit": f"Lỗi định dạng ở {region}", "lnk": "#", "brf": f"AI nhả sai cấu trúc. Text gốc: {error_msg[:80]}...", "ins": str(e)}]

def generate_html_report(news_data, outlook):
    """XUẤT FILE: Tạo báo cáo HTML độc lập"""
    now_str = datetime.now().strftime("%H:%M - %d/%m/%Y")
    html = f"""
    <html><head><meta charset="utf-8"><title>Radar Chiến Lược - {now_str}</title>
    <style>
        body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; max-width: 1000px; margin: 0 auto; padding: 20px; background: #f4f7f6; }}
        h1 {{ color: #0056b3; border-bottom: 2px solid #0056b3; padding-bottom: 10px; }}
        .macro {{ background: #111; color: #00ff41; padding: 20px; border-radius: 8px; font-family: monospace; margin-bottom: 30px; line-height: 1.6; }}
        .region-title {{ color: #d9534f; border-bottom: 1px solid #ccc; margin-top: 30px; }}
        .card {{ background: #fff; padding: 15px; border-radius: 8px; margin-bottom: 15px; border-left: 4px solid #0056b3; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
        .cat {{ background: #343a40; color: #fff; padding: 3px 8px; font-size: 11px; border-radius: 3px; }}
        .title {{ font-size: 16px; font-weight: bold; margin: 10px 0; }}
        .title a {{ color: #0056b3; text-decoration: none; }}
        .insight {{ background: #e2eafc; padding: 8px; border-left: 3px solid #0056b3; font-style: italic; font-size: 13px; margin-top: 10px; }}
    </style></head><body>
    <h1>🌍 Báo Cáo Radar Chiến Lược Toàn Cầu</h1>
    <p><i>Cập nhật lúc: {now_str}</i></p>
    <h2>👁️ Nhận Định Vĩ Mô</h2>
    <div class="macro">{outlook.replace(chr(10), '<br>')}</div>
    """
    for region, items in news_data.items():
        html += f"<h2 class='region-title'>📍 {region}</h2>"
        for item in items:
            html += f"""
            <div class="card">
                <div><span class="cat">{item.get('cat', 'Chung')}</span> | <b>{item.get('src', 'Nguồn')}</b></div>
                <div class="title"><a href="{item.get('lnk', '#')}" target="_blank">{item.get('tit', 'Tiêu đề')}</a></div>
                <div style="font-size:14px;">{item.get('brf', '')}</div>
                <div class="insight">💡 Phân tích: {item.get('ins', '')}</div>
            </div>"""
    html += "</body></html>"
    return html

# ==========================================
# 5. GIAO DIỆN CÀI ĐẶT (SIDEBAR)
# ==========================================
with st.sidebar:
    st.header("⚙️ Cài đặt Kiến trúc Lai")
    st.caption("Mở bảng này để nhập API Key")
    groq_key = st.text_input("1. Groq API Key (Quét tin):", type="password")
    gemini_key = st.text_input("2. Gemini API Key (Bộ não vĩ mô/Chat):", type="password")
    
    st.divider()
    selected_regions = st.multiselect("Vùng theo dõi:", list(RSS_FEEDS.keys()), default=list(RSS_FEEDS.keys())[:3])
    selected_topics = st.multiselect("Lĩnh vực trọng tâm:", CATEGORIES, default=["Kinh tế", "Chính trị", "Công nghệ & AI"])
    top_n_option = st.radio("Số tin hiển thị mỗi vùng:", [5, 10, 20], horizontal=True, index=0)
    
    run_btn = st.button("🚀 CẬP NHẬT (HYBRID MODE)", type="primary", use_container_width=True)

# ==========================================
# 6. HIỂN THỊ CHÍNH & LUỒNG CHẠY
# ==========================================
st.title("🌍 Radar Chiến Lược Toàn Cầu (Hybrid)")

if run_btn:
    if not groq_key or not gemini_key: st.error("Vui lòng nhập ĐỦ CẢ 2 API Key ở menu bên trái!")
    elif not selected_regions or not selected_topics: st.warning("Chọn ít nhất 1 vùng và 1 lĩnh vực!")
    else:
        with st.spinner("🔄 Llama 3.3 (Groq) đang quét và tóm tắt tin tức tốc độ cao..."):
            st.session_state.news_store = {}
            st.session_state.raw_news_store = {}
            st.session_state.chat_history = [] 
            
            # GIAI ĐOẠN 1: GROQ LÀM CÔNG NHÂN TÓM TẮT
            for region in selected_regions:
                raw_list = fetch_latest_news(RSS_FEEDS[region], max_items_per_url=20)
                if raw_list:
                    st.session_state.raw_news_store[region] = raw_list
                    st.session_state.news_store[region] = groq_analyze_worker(groq_key, raw_list, region, selected_topics, top_n_option)
            
        with st.spinner("🧠 Gemini đang đọc dữ liệu để đúc kết vĩ mô..."):
            # GIAI ĐOẠN 2: GEMINI LÀM BỘ NÃO VĨ MÔ
            genai.configure(api_key=gemini_key)
            model_macro = genai.GenerativeModel('gemini-2.5-flash')
            try:
                st.session_state.outlook_store = model_macro.generate_content(
                    f"Tổng hợp nhận định vĩ mô thế giới dựa trên các tin tức sau: {json.dumps(st.session_state.news_store)}",
                    safety_settings=SAFE_SETTINGS
                ).text
            except Exception as e:
                st.session_state.outlook_store = f"⚠️ Lỗi Gemini: {str(e)}"

# ==========================================
# 7. RENDER KẾT QUẢ & NÚT XUẤT HTML
# ==========================================
if st.session_state.news_store:
    # --- TÍNH NĂNG XUẤT FILE HTML ---
    html_content = generate_html_report(st.session_state.news_store, st.session_state.outlook_store)
    st.download_button(
        label="📥 TẢI BÁO CÁO HTML (ĐỌC OFFLINE)",
        data=html_content,
        file_name=f"Radar_Chien_Luoc_{datetime.now().strftime('%Y%m%d_%H%M')}.html",
        mime="text/html",
        type="secondary",
        use_container_width=True
    )
    st.markdown("<br>", unsafe_allow_html=True)
    
    # Render các Tab Tin tức
    tab_list = st.tabs(list(st.session_state.news_store.keys()))
    for i, region in enumerate(st.session_state.news_store.keys()):
        with tab_list[i]:
            for item in st.session_state.news_store[region]:
                st.markdown(f"""
                <div class="news-card">
                    <div class="news-header">
                        <span class="news-category">{item.get('cat', 'Chung')}</span>
                        <b>{item.get('src', 'Nguồn')}</b>
                    </div>
                    <a href="{item.get('lnk', '#')}" target="_blank" class="news-title-link">{item.get('tit', 'Tiêu đề')} 🔗</a>
                    <div class="news-brief">{item.get('brf', '')}</div>
                    <div class="news-insight">💡 <b>Phân tích:</b> {item.get('ins', '')}</div>
                </div>
                """, unsafe_allow_html=True)
                
            st.markdown("---")
            with st.expander(f"📂 Xem toàn bộ dữ liệu gốc ({len(st.session_state.raw_news_store.get(region, []))} tin đã kéo về)"):
                for idx, raw_item in enumerate(st.session_state.raw_news_store.get(region, [])):
                    st.markdown(f"<div class='raw-news-item'>{idx + 1}. <a href='{raw_item['link']}' target='_blank'>{raw_item['raw_title']}</a></div>", unsafe_allow_html=True)
    
    # Render Nhận định Vĩ mô
    st.markdown("### 📡 NHẬN ĐỊNH VĨ MÔ (By Gemini 2.5 Flash)")
    st.markdown(f'<div class="market-outlook">{st.session_state.outlook_store}</div>', unsafe_allow_html=True)

    # Render Chat Assistant
    st.markdown('<div class="chat-container">', unsafe_allow_html=True)
    st.subheader("💬 Trợ lý Gemini Chuyên Sâu")
    
    for msg in st.session_state.chat_history:
        with st.chat_message(msg["role"]): st.write(msg["content"])
        
    if chat_input := st.chat_input("VD: Tóm tắt cho tôi xu hướng công nghệ lõi hôm nay?"):
        st.session_state.chat_history.append({"role": "user", "content": chat_input})
        with st.chat_message("user"): st.write(chat_input)
        
        with st.chat_message("assistant"):
            try:
                genai.configure(api_key=gemini_key) 
                chat_model = genai.GenerativeModel('gemini-2.5-flash')
                res = chat_model.generate_content(
                    f"Dữ liệu hôm nay: {json.dumps(st.session_state.news_store)}\nTrả lời: {chat_input}", 
                    safety_settings=SAFE_SETTINGS
                )
                st.write(res.text)
                st.session_state.chat_history.append({"role": "assistant", "content": res.text})
            except Exception as e:
                st.error(f"Lỗi kết nối Gemini: {e}")
    st.markdown('</div>', unsafe_allow_html=True)