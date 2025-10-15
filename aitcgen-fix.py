import streamlit as st
import os
import tempfile
import datetime
import time 
from google import genai
from google.genai import types
from dotenv import load_dotenv

# Muat variabel lingkungan dari file .env (jika ada)
load_dotenv() 

# --- KONSTANTA DEFAULT UNTUK TEST CASE ---
DEFAULT_STATUS = "Draft"
DEFAULT_ESTIMATED_TIME = "00:00"
DEFAULT_AUTOMATION = "To be Automate"

# --- FUNGSI UTILITY WAKTU ---
def format_duration(seconds: float) -> str:
    """Mengubah detik menjadi format HH:MM:SS"""
    if seconds < 0:
        return "00:00:00"
    
    td = datetime.timedelta(seconds=seconds)
    total_seconds = int(td.total_seconds())
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60
    
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


# --- FUNGSI GEMINI API CORE ---

@st.cache_resource
def get_gemini_client(api_key):
    """Mendapatkan Gemini Client (di-cache untuk efisiensi)"""
    if not api_key:
        return None
    try:
        return genai.Client(api_key=api_key)
    except Exception:
        return None

def upload_files_to_gemini(client: genai.Client, uploaded_files: list) -> list:
    """Mengunggah file dari Streamlit ke Gemini API."""
    uploaded_gemini_files = []
    with st.spinner('Sistem sedang dipersiapkan.....'):
        with tempfile.TemporaryDirectory() as temp_dir:
            for file in uploaded_files:
                file_path = os.path.join(temp_dir, file.name)
                
                with open(file_path, "wb") as f:
                    f.write(file.getbuffer())
                
                try:
                    file_obj = client.files.upload(file=file_path)
                    uploaded_gemini_files.append(file_obj)
                except Exception as e:
                    st.error(f"Gagal mengunggah {file.name} ke Gemini: {e}")
                
    return uploaded_gemini_files

def generate_test_cases_with_ai(client: genai.Client, user_prompt: str, files: list) -> tuple[str, str, float]:
    """Memanggil Gemini API dan mengukur waktu eksekusi."""
    
    system_instruction = (
        "You are an expert QA Engineer specialized in generating structured test cases. "
        "Your output MUST be a raw CSV string with the following columns: "
        "Name,Status,Precondition,Objective,Estimated Time,Labels,Coverage (Issues),Automation,Test Type,Test Script (BDD). "
        
        "**STRICT FORMATTING AND CONTENT RULES:**\n"
        "1. **Language:** All text, including BDD Gherkin steps, MUST be in English.\n"
        "2. **Figma/UI Consistency:** All text related to UI elements (Nama Menu, Nama Sub Menu, Button, Nama Kolom, Error Message) used in the 'Name' and 'Test Script (BDD)' columns MUST be copied verbatim (disesuaikan) from the provided Figma/Mockup images and documents.\n"
        "3. **Default Values:** Use the following values for all generated test cases:\n"
        f"   - Status: '{DEFAULT_STATUS}'\n"
        f"   - Estimated Time: '{DEFAULT_ESTIMATED_TIME}'\n"
        f"   - Automation: '{DEFAULT_AUTOMATION}'\n"
        "4. **Name Format:** The Name column MUST follow the format: [Positive/Negative]-[WEB]-[DPIA][Notification] - [Description]. Example: '[Positive]-[WEB]-[DPIA][Notification] - Able to View List Role Management and [Negative]-[WEB]-[DPIA][Notification]' - 'Unable to View List Role Management'.\n"
        "4a. **Name Punctuation:** The description part in the 'Name' column MUST NOT end with a period (titik) or any trailing punctuation.\n"
        "5. **Test Type:** This column MUST be either 'Positive' or 'Negative', matching the Name prefix.\n"
        "6. **CSV Structure:** Use double quotes (\") to enclose text containing commas or newlines (like the Test Script). The first line MUST be the header row."
        "7. **BDD Format (Test Script):** The 'Test Script (BDD)' column MUST ONLY contain the step definitions (**Given, When, Then, And, But**). DO NOT include the **'Scenario:'** keyword. Each test case must be a single block of steps, starting with **Given**, followed by **When**, and ending with **Then**. Use **And** or **But** to chain additional steps within the single block. The structure must be: ONE 'Given', ONE 'When', ONE 'Then'."
        "8. **BDD Wording Consistency:** All occurrences of the first-person pronoun **'I'** (including 'I am', 'I want', 'I click', etc.) in the 'Test Script (BDD)' column **MUST** be replaced with the subject **'the user'**. For example, 'Given I am logged in' becomes **'Given the user is logged in'** or **'Given the user logs in'**. Ensure all subsequent verbs are grammatically correct when using 'the user' (singular third person)."
        "9. **RAW OUTPUT:** The final output MUST be the raw CSV string and **MUST NOT** be enclosed within any Markdown code block delimiters (triple backticks, i.e., ```). The first character of the output MUST be the quote (\") or the first letter of the header column 'Name'."
       
        "\nAnalyze the provided documents and the user's Acceptance Criteria (AC) carefully to generate the necessary content for the Precondition, Objective, Labels, and Test Script (BDD), strictly adhering to all rules."
    )

    contents = files + [user_prompt]
    
    with st.spinner('AI sedang menganalisis dokumen dan menghasilkan Test Case.....'):
        
        start_time_dt = datetime.datetime.now()
        start_time_str = start_time_dt.strftime("%H:%M:%S")
        start_time_seconds = time.time()
        
        try:
            response = client.models.generate_content(
                model='gemini-2.5-flash',
                contents=contents,
                config=types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    temperature=0.2 
                )
            )
            end_time_seconds = time.time()
            duration_seconds = end_time_seconds - start_time_seconds
            
            return response.text, start_time_str, duration_seconds
            
        except Exception as e:
            st.error(f"Gagal memanggil Gemini API: {e}") 
            return f"[ERROR] Gagal memanggil Gemini API: {e}", start_time_str, 0.0

def delete_uploaded_files(client: genai.Client, files: list):
    """Menghapus file yang sudah diunggah dari server Gemini."""
    for file_obj in files:
        try:
            client.files.delete(name=file_obj.name)
        except Exception:
            pass 

# --- STREAMLIT INTERFACE ---

st.set_page_config(page_title="AI Test Case Generator", layout="wide")

# Inisialisasi session state untuk status loading dan hasil
if 'is_generating' not in st.session_state:
    st.session_state['is_generating'] = False
if 'csv_result' not in st.session_state:
    st.session_state['csv_result'] = None
if 'metadata' not in st.session_state:
    st.session_state['metadata'] = {}

# Tentukan status disabled global: True jika sedang generate ATAU hasil sudah ada di layar.
is_disabled_global = (st.session_state.is_generating or st.session_state.csv_result is not None)

# Sidebar untuk Konfigurasi Kunci API
st.sidebar.title("🔑 Konfigurasi API")
initial_api_key = os.getenv("GEMINI_API_KEY", "")
api_key = st.sidebar.text_input(
    "Masukkan Kunci API Gemini Anda:", 
    value=initial_api_key, 
    type="password",
    # DISABLED JIKA SEDANG GENERATE ATAU JIKA HASIL ADA
    disabled=is_disabled_global 
)
st.sidebar.markdown("""
<small>Kunci API Anda tidak disimpan. Dapatkan kunci gratis di [Google AI Studio](https://aistudio.google.com/)</small>
""", unsafe_allow_html=True)

# Main App
# st.title("🧪 AI Test Case Generator")
st.title("AI Test Case Generator")
st.markdown("1. Unggah dokumen (PRD/Figma) dan berikan *Acceptance Criteria* (AC) untuk menghasilkan *Test Case* otomatis dalam format CSV.")

# File Uploader
uploaded_files = st.file_uploader(
    "1. Unggah Dokumen Pendukung (PDF, JPG, JPEG, PNG)",
    type=['pdf', 'jpg', 'jpeg', 'png'],
    accept_multiple_files=True,
    # DISABLED JIKA SEDANG GENERATE ATAU JIKA HASIL ADA
    disabled=is_disabled_global 
)

# Prompt Input
st.markdown("---")
#st.subheader("Masukkan *Acceptance Criteria* (AC) dan Detail Fungsionalitas")
st.markdown("2. Masukkan *Acceptance Criteria* (AC) dan Detail Fungsionalitas")
user_prompt = st.text_area(
    "Tempelkan di sini AC, skenario, dan detail yang perlu diuji:",
    height=300,
    placeholder="Contoh:\nBuatkan test case yang bisa dibuat test case dari file ini dengan menggabungkannya. Baca semua text dari image dan juga text dari pdf nya. Test case hanya untuk Notification for DPIA document saja serta spesifik user DPO Officer & DPO Supervisor. Jika terdapat informasi mengenai backward compatibility buatkan juga test casenya, gunakan Labels hanya “qa-arief” saja.\n",
    # DISABLED JIKA SEDANG GENERATE ATAU JIKA HASIL ADA
    disabled=is_disabled_global 
)

# Tombol Generate
st.markdown("---")

# Tombol Generate
if st.button("🚀 Generate Test Cases", type="primary", use_container_width=True, disabled=is_disabled_global):
    
    # --- RESET HASIL LAMA SAAT TOMBOL INI DIKLIK ---
    st.session_state.csv_result = None
    st.session_state.metadata = {}
    
    # --- LOGIKA GENERATE DIMULAI ---
    if not api_key:
        st.error("Masukkan Kunci API Gemini Anda di *sidebar* untuk melanjutkan.")
    elif not user_prompt.strip():
        st.error("Masukkan *Acceptance Criteria* (AC) di kotak teks.")
    else:
        # PENTING: Set status loading dan RERUN untuk menonaktifkan input
        st.session_state.is_generating = True 
        st.rerun() 

# --- Logika Eksekusi Proses Utama (hanya berjalan saat is_generating=True) ---
if st.session_state.is_generating:
    
    client = get_gemini_client(api_key)
    gemini_files = [] 
    
    if client:
        try:
            # 1. Upload Files
            gemini_files = upload_files_to_gemini(client, uploaded_files)
            
            # 2. Generate Test Case 
            if gemini_files or not uploaded_files: 
                
                csv_result, start_time_str, duration_seconds = generate_test_cases_with_ai(client, user_prompt, gemini_files)
                
                if "[ERROR]" not in csv_result:
                    st.session_state.csv_result = csv_result
                    st.session_state.metadata = {
                        "start_time": start_time_str,
                        "duration": format_duration(duration_seconds)
                    }
                else:
                    st.error("Gagal menghasilkan test case. Lihat pesan error di atas.")
                
        except Exception as e:
            st.error(f"Terjadi kesalahan fatal selama proses: {e}")
        
        finally:
            # 4. Cleanup dan Reset Status
            delete_uploaded_files(client, gemini_files)
            st.session_state.is_generating = False # Mengaktifkan kembali logika is_disabled_global
            st.rerun() 
    else:
        st.error("Gagal menginisialisasi Gemini Client. Cek kembali Kunci API Anda.")
        st.session_state.is_generating = False
        st.rerun() 

# --- Logika Display Hasil (Berjalan setelah proses selesai dan is_generating=False) ---
if st.session_state.csv_result:
    st.markdown("---")
    st.subheader("🎉 Output Hasil Generate")
    
    metadata = st.session_state.metadata
    
    st.markdown(f"""
    | Metrik | Detail |
    | :--- | :--- |
    | **Waktu Mulai Generate** | `{metadata['start_time']}` |
    | **Durasi Proses** | `{metadata['duration']}` |
    """, unsafe_allow_html=True)
    
    st.success("Test Case berhasil dibuat!")
    
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    file_name_with_timestamp = f"test_cases_{timestamp}.csv"
    
    # Menggunakan columns agar tombol download dan clear berdampingan
    col1, col2 = st.columns([1, 1])
    
    # Tombol Download di kolom pertama (ENABLE)
    with col1:
        st.download_button(
            label="📥 Download Test Cases (CSV)",
            data=st.session_state.csv_result.encode('utf-8'),
            file_name=file_name_with_timestamp,
            mime="text/csv",
            use_container_width=True 
        )
    
    # Tombol Clear Output di kolom kedua (ENABLE)
    with col2:
        # Tombol ini mereset csv_result menjadi None, yang akan MENGAKTIFKAN KEMBALI SEMUA INPUT
        if st.button("🗑️ Clear Output", type="secondary", use_container_width=True):
            st.session_state.csv_result = None
            st.session_state.metadata = {}
            st.rerun() 

    st.code(st.session_state.csv_result, language='csv')