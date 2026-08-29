# -*- coding: utf-8 -*-
import os
import sys
import io
import base64
import json
from datetime import datetime
from collections import defaultdict

# 設定系統環境變數以支援 UTF-8 編碼
os.environ["PYTHONIOENCODING"] = "utf-8"
os.environ["LC_ALL"] = "en_US.UTF-8"
os.environ["LANG"] = "en_US.UTF-8"

import streamlit as st
import requests
from supabase import create_client, Client
from gtts import gTTS
from google import genai
from google.genai import types

# --- 1. 初始化 Supabase 與 Gemini 連線 ---
@st.cache_resource
def init_supabase() -> Client:
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_KEY"]
    return create_client(url, key)

try:
    supabase = init_supabase()
except Exception as e:
    st.error("⚠️ Supabase 連線失敗，請檢查 Streamlit Secrets 設定。")
    st.stop()

# 初始化 Gemini Client
gemini_client = None
if "GEMINI_API_KEY" in st.secrets and st.secrets["GEMINI_API_KEY"]:
    try:
        gemini_client = genai.Client(api_key=st.secrets["GEMINI_API_KEY"])
    except Exception as e:
        st.warning("⚠️ Gemini API 初始化失敗，將降級使用傳統字典 API。")

# --- 2. 側邊欄控制項：語音模組與語速拉霸 ---
st.sidebar.title("⚙️ 播放與系統設定")

tts_engine = st.sidebar.radio(
    "🎙️ 選擇語音發音模組：",
    ["Web Speech (裝置內建/無延遲)", "Google TTS (雲端高清/發音標準)"]
)

speech_rate = st.sidebar.slider(
    "🎛️ 調整播放語速：",
    min_value=0.5,
    max_value=1.5,
    value=0.85,
    step=0.05,
    help="0.5x 為慢速朗讀，1.0x 為正常語速，適合女兒練習聽力與跟讀。"
)

# --- 3. 核心功能：發音快取、發音渲染器與 AI 字典解析 ---
@st.cache_data(show_spinner=False, max_entries=500, ttl=86400)
def get_gtts_audio_b64(text: str, slow: bool) -> str:
    """快取 gTTS 生成結果（帶有容量上限與 24 小時自動清理機制）"""
    tts = gTTS(text=text, lang='en', slow=slow)
    fp = io.BytesIO()
    tts.write_to_fp(fp)
    fp.seek(0)
    return base64.b64encode(fp.read()).decode()

def render_audio_player(text: str, rate: float, engine: str):
    """根據選定的模組與語速渲染 HTML5 發音播放器"""
    clean_text = text.replace("'", "\\'").replace('"', '\\"').replace("\n", " ")
    
    # 方案 A：Google TTS
    if "Google TTS" in engine:
        try:
            audio_b64 = get_gtts_audio_b64(text, rate < 0.8)
            html_code = f"""
            <audio id="audio_{hash(text)}" src="data:audio/mp3;base64,{audio_b64}"></audio>
            <button onclick="document.getElementById('audio_{hash(text)}').play()" 
                    style="padding: 7px 15px; border-radius: 8px; border: 1px solid #2196F3; background-color: #e3f2fd; cursor: pointer; font-size: 14px; font-weight: bold; color: #0d47a1;">
                🔊 播放發音 (Google TTS - {rate}x)
            </button>
            """
            st.components.v1.html(html_code, height=45)
            return
        except Exception:
            st.warning("Google TTS 請求頻繁被擋，已自動切換至 Web Speech 發音。")
            
    # 方案 B：Web Speech API
    html_code = f"""
    <button onclick="speak('{clean_text}')" 
            style="padding: 7px 15px; border-radius: 8px; border: 1px solid #4CAF50; background-color: #f1f9f1; cursor: pointer; font-size: 14px; font-weight: bold; color: #2e7d32;">
        🔊 播放發音 (Web Speech - {rate}x)
    </button>
    <script>
    function speak(text) {{
        window.speechSynthesis.cancel();
        var msg = new SpeechSynthesisUtterance(text);
        msg.lang = 'en-US';
        msg.rate = {rate};
        msg.pitch = 1.0;
        window.speechSynthesis.speak(msg);
    }}
    </script>
    """
    st.components.v1.html(html_code, height=45)

def fetch_word_details(word: str):
    """優先使用 Gemini AI 生成自然例句與英英/中文解釋；若無 Gemini 則使用傳統 API 備援"""
    clean_word = word.strip().lower()

    # --- 優先方案：Gemini AI 生成 ---
    if gemini_client:
        try:
            prompt = f"""
            Please provide dictionary details for the English word: "{clean_word}".
            Return the result ONLY in strict JSON format with the following keys:
            - "word": string (lowercase)
            - "phonetic": string (IPA phonetic notation, e.g., /əbˈzəluːʃn/)
            - "definition": string (Clear English definition with parts of speech and Traditional Chinese translations. Format nicely using Markdown with 📌 for parts of speech)
            - "example": string (A natural, authentic, context-rich example sentence showing how the word is really used in modern English)

            Example JSON format:
            {{
                "word": "absolution",
                "phonetic": "/ˌæb.səˈluː.ʃən/",
                "definition": "📌 **[NOUN]** 赦免；解職；罪過的赦免\\n(1) Formal release from guilt, obligation, or punishment.\\n(2) Official forgiveness of sins declared by a priest.",
                "example": "The priest granted him absolution after he confessed his sins."
            }}
            """
            response = gemini_client.models.generate_content(
                model='gemini-2.5-flash',
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json"
                )
            )
            res_json = json.loads(response.text)
            return {
                "word": clean_word,
                "phonetic": res_json.get("phonetic", f"/{clean_word}/"),
                "definition": res_json.get("definition", "無提供解釋"),
                "example": res_json.get("example", f"Please practice using the word '{clean_word}'.")
            }
        except Exception as e:
            st.warning(f"Gemini API 查詢失敗 ({e})，切換至傳統字典 API。")

    # --- 備援方案 1：Free Dictionary API ---
    api_url = f"https://api.dictionaryapi.dev/api/v2/entries/en/{clean_word}"
    try:
        res = requests.get(api_url, timeout=5)
        if res.status_code == 200:
            data = res.json()[0]
            phonetic = data.get("phonetic", "")
            meanings = data.get("meanings", [])
            
            definitions_list = []
            example = ""
            first_pos = ""
            
            for m in meanings:
                part_of_speech = m.get("partOfSpeech", "")
                if not first_pos:
                    first_pos = part_of_speech.upper()
                defs = m.get("definitions", [])
                
                sub_defs = []
                for idx, d in enumerate(defs[:3]):
                    def_text = d.get("definition", "")
                    if def_text:
                        sub_defs.append(f"({idx+1}) {def_text}")
                    if not example and d.get("example"):
                        example = d.get("example")
                        
                if sub_defs:
                    definitions_list.append(f"📌 **[{part_of_speech.upper()}]**\n" + "\n".join(sub_defs))
            
            full_definition = "\n\n".join(definitions_list) if definitions_list else "無提供英英解釋"
            
            if example:
                final_example = example
            else:
                if "ADJ" in first_pos or "ADJECTIVE" in first_pos:
                    final_example = f"His {clean_word} tone of voice made everyone feel quiet."
                elif "NOUN" in first_pos or "N" in first_pos:
                    final_example = f"The textbook explained the meaning of '{clean_word}' clearly."
                elif "VERB" in first_pos or "V" in first_pos:
                    final_example = f"They tried to {clean_word} as instructed by the teacher."
                else:
                    final_example = f"The passage described the situation using the word '{clean_word}'."
            
            return {
                "word": clean_word, 
                "phonetic": phonetic, 
                "definition": full_definition, 
                "example": final_example
            }
    except Exception:
        pass

    # --- 備援方案 2：Datamuse API ---
    try:
        fallback_url = f"https://api.datamuse.com/words?sp={clean_word}&md=d"
        res_fb = requests.get(fallback_url, timeout=5)
        if res_fb.status_code == 200 and res_fb.json():
            data = res_fb.json()[0]
            defs = data.get("defs", [])
            
            if defs:
                definitions_list = []
                first_pos = "DEF"
                for idx, d in enumerate(defs[:3]):
                    parts = d.split("\t")
                    pos = parts[0].upper() if len(parts) > 1 else "DEF"
                    if idx == 0:
                        first_pos = pos
                    def_text = parts[1] if len(parts) > 1 else parts[0]
                    definitions_list.append(f"📌 **[{pos}]**\n(1) {def_text}")
                
                full_definition = "\n\n".join(definitions_list)
                
                if "ADJ" in first_pos:
                    final_example = f"His {clean_word} tone of voice made everyone feel uncomfortable."
                elif "N" in first_pos:
                    final_example = f"Understanding the concept of '{clean_word}' is important in this topic."
                elif "V" in first_pos:
                    final_example = f"They attempted to {clean_word} the plan despite the difficulties."
                else:
                    final_example = f"The author described the scene as {clean_word}."
                
                return {
                    "word": clean_word,
                    "phonetic": f"/{clean_word}/",
                    "definition": full_definition,
                    "example": final_example
                }
    except Exception:
        pass

    # --- 備援方案 3：保底備援 ---
    return {
        "word": clean_word,
        "phonetic": f"/{clean_word}/",
        "definition": f"📌 **[WORD]**\n(1) A vocabulary word: {clean_word}.",
        "example": f"The passage described the setting using the word '{clean_word}'."
    }

def render_speech_recognizer(target_word: str):
    """利用 Web Speech API 進行網頁端即時口說辨識 (STT)"""
    clean_target = target_word.lower().replace("'", "\\'").replace('"', '\\"')
    html_code = f"""
    <div style="margin-top: 5px;">
        <button id="start-btn" onclick="startDictation()" style="padding: 10px 18px; border-radius: 8px; background-color: #2196F3; color: white; border: none; cursor: pointer; font-weight: bold; font-size: 15px;">
            🎤 開始口說答題
        </button>
        <p id="result-text" style="font-weight: bold; margin-top: 10px; color: #333; font-size: 15px;">尚未錄音 (點擊按鈕後請朗讀單字)</p>
    </div>
    <script>
    function startDictation() {{
        var SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
        if (!SpeechRecognition) {{
            alert("您的瀏覽器不支援語音辨識。iPad/iPhone 請使用 iOS 14.5 以上的 Safari，Mac 請使用 Chrome 或 Safari。");
            return;
        }}

        var recognition = new SpeechRecognition();
        recognition.lang = 'en-US';
        recognition.interimResults = false;
        recognition.maxAlternatives = 1;

        var resultEl = document.getElementById('result-text');
        resultEl.innerText = "🎙️ 聆聽中...請清楚朗讀單字";
        resultEl.style.color = "#FF9800";

        recognition.onresult = function(event) {{
            var spokenText = event.results[0][0].transcript.toLowerCase().trim();
            spokenText = spokenText.replace(/[.,?!]/g, "");
            var target = "{clean_target}";
            
            if (spokenText === target || spokenText.includes(target)) {{
                resultEl.innerText = "✅ 正確！妳說的是: " + spokenText;
                resultEl.style.color = "#4CAF50";
            }} else {{
                resultEl.innerText = "❌ 答案不符。妳說的是: " + spokenText;
                resultEl.style.color = "#F44336";
            }}
        }};

        recognition.onerror = function(event) {{
            console.error("Speech Recognition Error:", event.error);
            if (event.error === 'not-allowed') {{
                resultEl.innerText = "🚫 麥克風權限被拒絕！請點擊網址列左側鎖頭/設定開啟麥克風權限。";
            }} else if (event.error === 'no-speech') {{
                resultEl.innerText = "⚠️ 沒有偵測到聲音，請再試一次並提高音量。";
            }} else {{
                resultEl.innerText = "❌ 辨識失敗 (" + event.error + ")，請再試一次。";
            }}
            resultEl.style.color = "#F44336";
        }};

        try {{
            recognition.start();
        }} catch(e) {{
            resultEl.innerText = "⚠️ 錄音啟動中，請再點一次按鈕。";
        }}
    }}
    </script>
    """
    st.components.v1.html(html_code, height=100)

# --- 4. UI 主頁面與角色選擇 ---
st.set_page_config(page_title="英單特訓王", page_icon="🔤", layout="wide")
st.title("🔤 英文單字雲端特訓平台")

try:
    users_data = supabase.table("users").select("*").execute().data
except Exception as e:
    st.error("無法存取 users 資料表，請確認已在 Supabase 執行 SQL 建表指令與授權。")
    st.stop()

if not users_data:
    st.warning("資料庫中無使用者資料，請確認 Supabase SQL Editor 是否已寫入預設使用者。")
    st.stop()

st.sidebar.divider()
user_names = [u["name"] for u in users_data]
current_user_name = st.sidebar.selectbox("👤 請選擇使用者登入：", user_names)
current_user = next(u for u in users_data if u["name"] == current_user_name)

st.sidebar.write(f"目前身分：**{'管理者 (媽媽)' if current_user['role'] == 'mom' else '學生 (複習與測驗)'}**")

# --- 5. 媽媽介面 (管理者) ---
if current_user["role"] == "mom":
    st.header("👩‍🏫 媽媽管理後台")
    tab1, tab2, tab3 = st.tabs(["➕ 新增單字進資料庫", "📚 查看現有單字庫", "📊 查看與稽核成績"])
    
    with tab1:
        new_word = st.text_input("請輸入要新增的英文單字：").strip()
        if st.button("自動查詢並加入資料庫"):
            if new_word:
                details = fetch_word_details(new_word)
                if details:
                    supabase.table("words").upsert(
                        {
                            "word": details["word"],
                            "definition": details["definition"],
                            "example": details["example"],
                            "phonetic": details["phonetic"]
                        },
                        on_conflict="word"
                    ).execute()
                    
                    words_in_db = supabase.table("words").select("id").eq("word", details["word"]).execute().data
                    if words_in_db:
                        w_id = words_in_db[0]["id"]
                        students = [u for u in users_data if u["role"] == "student"]
                        for s in students:
                            exist_record = supabase.table("user_word_progress").select("id").eq("user_id", s["id"]).eq("word_id", w_id).execute().data
                            if not exist_record:
                                supabase.table("user_word_progress").insert({
                                    "user_id": s["id"],
                                    "word_id": w_id,
                                    "passed": False
                                }).execute()
                            
                    st.success(f"單字 **{new_word}** 已成功更新/加入資料庫！")
                    st.markdown("**英英解釋（多重詞性與字義）：**")
                    st.markdown(details["definition"])
                    st.write("**經典例句：**", details["example"])
                    render_audio_player(new_word, speech_rate, tts_engine)
                else:
                    st.error("查詢時發生預料外錯誤。")
            else:
                st.warning("請先輸入單字！")

    # 查看現有單字庫
    with tab2:
        st.subheader("📖 資料庫現有單字清單 (依字首 A-Z 分類)")
        try:
            all_words = supabase.table("words").select("*").order("word", desc=False).execute().data
            if all_words:
                st.write(f"目前資料庫共有 **{len(all_words)}** 個單字：")
                
                search_query = st.text_input("🔍 搜尋資料庫中的單字：", "").strip().lower()
                filtered_words = [w for w in all_words if search_query in w["word"].lower()] if search_query else all_words
                
                grouped_words = defaultdict(list)
                for w in filtered_words:
                    first_letter = w["word"][0].upper() if w["word"] else "#"
                    grouped_words[first_letter].append(w)
                
                st.divider()
                
                for letter in sorted(grouped_words.keys()):
                    letter_words = grouped_words[letter]
                    st.markdown(f"### 🔠 字母 {letter} `({len(letter_words)} 個單字)`")
                    
                    for w in letter_words:
                        raw_date = w.get("created_at", "")
                        formatted_date = raw_date[:10] if raw_date else "未知日期"
                        
                        expander_label = f"🔤 {w['word']}   `{w.get('phonetic', '')}`   📅 加入日期：{formatted_date}"
                        
                        with st.expander(expander_label):
                            st.markdown("**發音選項：**")
                            render_audio_player(w["word"], speech_rate, tts_engine)
                            st.divider()
                            st.markdown("**英英解釋（包含所有詞性）：**")
                            st.markdown(w["definition"])
                            st.write("**經典例句：**", w["example"])
                            render_audio_player(w["example"], speech_rate, tts_engine)
                    st.divider()
            else:
                st.info("資料庫目前尚無任何單字，請至「新增單字進資料庫」頁籤建立第一個單字！")
        except Exception as e:
            st.error("無法讀取單字庫列表，請確認 Supabase 權限設定。")
                    
    with tab3:
        st.subheader("📋 兩姐妹單字審核與過關設定")
        students = [u for u in users_data if u["role"] == "student"]
        if students:
            selected_student_name = st.selectbox("選擇學生：", [s["name"] for s in students])
            selected_student = next(s for s in students if s["name"] == selected_student_name)
            
            progress_data = supabase.table("user_word_progress").select("id, passed, correct_count, wrong_count, words(word, definition, example)").eq("user_id", selected_student["id"]).execute().data
            
            if progress_data:
                for item in progress_data:
                    w_info = item["words"]
                    if not w_info:
                        continue
                    col1, col2, col3, col4 = st.columns([2, 3, 2, 2])
                    with col1:
                        st.write(f"**{w_info['word']}**")
                    with col2:
                        st.write(f"答對: `{item.get('correct_count', 0)}` 次 | 答錯: `{item.get('wrong_count', 0)}` 次")
                    with col3:
                        is_passed = st.checkbox("通過審核", value=item["passed"], key=f"check_{item['id']}")
                        if is_passed != item["passed"]:
                            supabase.table("user_word_progress").update({"passed": is_passed}).eq("id", item["id"]).execute()
                            st.rerun()
                    with col4:
                        render_audio_player(w_info["word"], speech_rate, tts_engine)
                    st.divider()
            else:
                st.info("該學生目前尚無單字練習紀錄。")

# --- 6. 姊姊/妹妹介面 (學生) ---
else:
    st.header(f"👧 {current_user['name']} 的單字學習小天地")
    tab1, tab2 = st.tabs(["🎴 單字卡卡片複習", "📝 單字測驗特訓"])
    
    student_words = supabase.table("user_word_progress").select("id, passed, correct_count, wrong_count, words(id, word, definition, example, phonetic)").eq("user_id", current_user["id"]).execute().data
    
    with tab1:
        st.subheader("📖 翻牌單字卡複習")
        unpassed_words = [w for w in student_words if w.get("words") and not w["passed"]]
        if not unpassed_words:
            st.balloons()
            st.success("🎉 太棒了！妳目前所有的單字都已經順利通過審核過關囉！")
        else:
            word_options = [w["words"]["word"] for w in unpassed_words]
            selected_w_name = st.selectbox("請選擇要複習的單字：", word_options)
            curr_w = next(w["words"] for w in unpassed_words if w["words"]["word"] == selected_w_name)
            
            st.markdown(f"### 🔤 單字： **{curr_w['word']}** `{curr_w.get('phonetic', '')}`")
            render_audio_player(curr_w["word"], speech_rate, tts_engine)
            
            with st.expander("點擊展開完整英英解釋與例句"):
                st.markdown("**英英解釋（包含所有詞性）：**")
                st.markdown(curr_w["definition"])
                st.write("**經典例句：**", curr_w["example"])
                render_audio_player(curr_w["example"], speech_rate, tts_engine)

    with tab2:
        st.subheader("🎯 英英辨析單字測驗")
        quiz_mode = st.radio("選擇測驗範圍：", ["本週未通過生字", "資料庫全單字庫測驗"], horizontal=True)
        
        valid_student_words = [w for w in student_words if w.get("words")]
        target_list = unpassed_words if quiz_mode == "本週未通過生字" else valid_student_words
        
        if not target_list:
            st.info("目前範圍內沒有可測驗的單字。")
        else:
            if "quiz_index" not in st.session_state:
                st.session_state.quiz_index = 0
                
            q_idx = st.session_state.quiz_index % len(target_list)
            q_item = target_list[q_idx]
            q_word_item = q_item["words"]
            p_id = q_item["id"]
            
            st.info("💡 **題目（英英解釋）：**")
            st.markdown(q_word_item['definition'])
            
            answer_type = st.radio("選擇答題方式：", ["鍵盤輸入拼字", "口說發音答題"], horizontal=True)
            
            if answer_type == "鍵盤輸入拼字":
                user_input = st.text_input("請拼寫出該英文單字：", key=f"quiz_input_{q_idx}").strip().lower()
                if st.button("提交答案"):
                    if user_input == q_word_item["word"].lower():
                        st.success("🎉 完全正確！太厲害了！")
                        render_audio_player(q_word_item["word"], speech_rate, tts_engine)
                        curr_correct = q_item.get("correct_count", 0) or 0
                        supabase.table("user_word_progress").update({"correct_count": curr_correct + 1}).eq("id", p_id).execute()
                    else:
                        st.error(f"❌ 答錯囉！正確答案是：**{q_word_item['word']}**")
                        render_audio_player(q_word_item["word"], speech_rate, tts_engine)
                        curr_wrong = q_item.get("wrong_count", 0) or 0
                        supabase.table("user_word_progress").update({"wrong_count": curr_wrong + 1}).eq("id", p_id).execute()
                        
            else:  # 口說答題
                st.write("請點擊下方按鈕，朗讀出該單字：")
                render_speech_recognizer(q_word_item["word"])
                st.write("聽正確發音：")
                render_audio_player(q_word_item["word"], speech_rate, tts_engine)
                
            st.divider()
            if st.button("下一題 ➡️"):
                st.session_state.quiz_index += 1
                st.rerun()
