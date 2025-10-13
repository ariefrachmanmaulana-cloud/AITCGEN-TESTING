import streamlit as st
import os
import tempfile
import datetime
import time 
import re 
import io # Import io untuk menangani string sebagai file
import csv # Import csv untuk parsing CSV string
from google import genai
from google.genai import types
from dotenv import load_dotenv

# Muat variabel lingkungan dari file .env (jika ada)
load_dotenv() 

# --- KONSTANTA DEFAULT UNTUK TEST CASE ---
DEFAULT_STATUS = "Draft"
DEFAULT_ESTIMATED_TIME = "00:00"
DEFAULT_AUTOMATION = "To be Automate"
# KONSTANTA DEFAULT BARU
DEFAULT_COVERAGE = "" # Kosongkan agar user bisa input
DEFAULT_LABELS = "" # Kosongkan agar user bisa input

# --- FUNGSI UTILITY WAKTU & CSV ---
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

def count_csv_rows(csv_string: str) -> int:
    """
    Menghitung jumlah baris data (bukan header) dalam string CSV.
    """
    try:
        # Gunakan StringIO untuk memperlakukan string sebagai file
        string_io = io.StringIO(csv_string)
        # Gunakan csv.reader untuk menangani berbagai format CSV (termasuk kutipan)
        reader = csv.reader(string_io)
        
        row_count = 0
        for _ in reader:
            row_count += 1
            
        # Kurangi 1 untuk header. Pastikan hasilnya tidak negatif.
        return max(0, row_count - 1)
    except Exception:
        # Jika terjadi error parsing, kembalikan 0
        return 0

# --- FUNGSI IDENTIFIKASI FITUR/MENU BARU ---

def extract_action_tag(prompt: str, default_tag: str = "GenericAction") -> str:
    """
    Mengidentifikasi Aksi/Fitur dari prompt pengguna (misal: Download, Notification).
    """
    
    # Daftarkan kata kunci fitur/menu/aksi yang sering muncul, 
    # diurutkan dari yang lebih spesifik/panjang
    keywords = [
        "Download", "Upload", "Create", "Edit", 
        "Delete", "Detail", "Role Management",
        "Notification", "Dashboard", "Settings", "Profile", "Report",
        "View List", "Filter", "Search", "Export", "Import"
    ]
    
    # Bersihkan prompt: lowercase, hilangkan karakter non-alphanumeric (kecuali spasi)
    cleaned_prompt = prompt.lower()
    
    # Cari kata kunci yang cocok
    for keyword in keywords:
        # Gunakan regex untuk mencari kata kunci sebagai kata utuh (word boundary)
        if re.search(r'\b' + re.escape(keyword.lower()) + r'\b', cleaned_prompt):
            # Mengembalikan kata kunci asli (dengan kapitalisasi seperti di list) yang paling spesifik/pertama ditemukan
            return keyword.replace(' ', '') 
            
    # Jika tidak ada yang cocok, gunakan default_tag
    return default_tag

def extract_project_acronym(prompt: str, default_acronym: str = "DPIA") -> str:
    """
    Mengidentifikasi Project Acronym/Menu Utama dari prompt pengguna (misal: DPIA, RoPA, Gap Analysis).
    """
    # Daftarkan kata kunci Project/Menu Utama yang sering muncul.
    acronyms = [
        "DPIA", "RoPA", "Gap Analysis", "CISO", "Risk Register", "Incident Report",
        "Privacy Notice", "Vendor Assessment", "Policy Management"
    ]

    # Gabungkan semua acronym menjadi satu regex pattern, 
    acronyms.sort(key=len, reverse=True)
    pattern = r'\b(' + '|'.join(re.escape(a.lower()) for a in acronyms) + r')\b'
    
    cleaned_prompt = prompt.lower()
    match = re.search(pattern, cleaned_prompt)

    if match:
        matched_text = match.group(0).upper()
        for acronym in acronyms:
             if acronym.upper() == matched_text:
                 return acronym.replace(' ', '')
        
    match_after_action = re.search(r'\b(download|create|edit|delete)\s+(\w+)', cleaned_prompt)
    if match_after_action and match_after_action.group(2).upper() not in ["USER", "ROLE", "DOCUMENT", "REPORT"]:
        return match_after_action.group(2).upper()

    return default_acronym 


# --- FUNGSI GEMINI API CORE ---

@st.cache_resource
def get_gemini_client(api_key):
    """
    Mendapatkan Gemini Client (di-cache untuk efisiensi) dan memvalidasi kunci API.
    Mengembalikan: genai.Client object jika valid, 'INVALID_KEY' jika gagal, atau None jika api_key kosong.
    """
    if not api_key:
        return None
    try:
        client = genai.Client(api_key=api_key)
        
        # VALIDASI KUNCI API: Panggilan ringan untuk memastikan koneksi dan kunci valid.
        try:
            # Memaksa panggilan API (misalnya, daftar model)
            client.models.list() 
        except Exception:
             # Jika terjadi error saat panggilan ini, asumsikan API Key tidak valid.
             return "INVALID_KEY" 
        
        return client
    except Exception:
        # Menangkap error saat inisialisasi Client (misalnya, masalah konfigurasi library)
        return "INVALID_KEY" 
    
    return None # Fallback


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

# FUNGSI GENERATOR DIPERBARUI DENGAN INSTRUKSI BARU
def generate_test_cases_with_ai(
    client: genai.Client, 
    user_prompt: str, 
    files: list, 
    platform_tag: str, 
    default_labels: str, 
    default_coverage: str
) -> tuple[str, str, float, str, str]:
    """Memanggil Gemini API dan mengukur waktu eksekusi, serta mengembalikan tag fitur."""
    
    # 1. EKSTRAKSI FITUR/MENU DARI PROMPT
    action_tag = extract_action_tag(user_prompt, default_tag="GenericAction")
    project_acronym_tag = extract_project_acronym(user_prompt, default_acronym="DPIA") 
    
    # 2. DEFINISIKAN SYSTEM INSTRUCTION DENGAN TAG YANG BARU
    
    platform_mapping = {
        "Website": "WEB", 
        "Back Office": "BO",
        "Android": "AND",
        "IOS": "IOS",
        "API": "API",
    }
    final_platform_tag = platform_mapping.get(platform_tag, "GENERIC")
    
    # MEMODIFIKASI SYSTEM INSTRUCTION SESUAI PERMINTAAN
    system_instruction = (
        "You are an expert QA Engineer specialized in generating structured test cases. "
        "Your output MUST be a raw CSV string with the following columns: "
        "Name,Status,Precondition,Objective,Estimated Time,Labels,Coverage (Issues),Automation,Test Type,Test Script (BDD). "
        
        "DOCUMENT ANALYSIS PRIORITY:\n"
        "1. MANDATORY CONTEXT: You MUST deeply analyze and integrate information from ALL provided documents (PDF, Figma/PNG/JPG/JPEG) to ensure the test cases are accurate and comprehensive.\n"
        "2. COMBINED ANALYSIS: Treat all documents and the user prompt as a single, combined source of truth. Use the UI elements, fields, error messages, and business logic described in the documents to fulfill the user's specific request/Acceptance Criteria (AC).\n"
        "3. VERBATIM EXTRACTION: Specifically, extract and use verbatim (sesuai) text from the Figma/UI images for: Menu Names, Button Labels, Column Headers, and Error Messages in the 'Name' and 'Test Script (BDD)' columns.\n"
        
        "STRICT FORMATTING AND CONTENT RULES:\n"
        "1. Language: All text, including BDD Gherkin steps, MUST be in English.\n"
        "2. Figma/UI Consistency: All text related to UI elements used in the 'Name' and 'Test Script (BDD)' columns MUST be copied verbatim (disesuaikan) from the provided Figma/Mockup images and documents, as described in the 'MANDATORY CONTEXT' above.\n"
        "3. Default Values: Use the following values for all generated test cases:\n"
        f"   - Status: '{DEFAULT_STATUS}'\n"
        f"   - Estimated Time: '{DEFAULT_ESTIMATED_TIME}'\n"
        f"   - Automation: '{DEFAULT_AUTOMATION}'\n"
        # DEFAULT BARU DARI INPUT USER
        f"   - Labels: '{default_labels}' (Gunakan nilai ini untuk semua baris jika Labels tidak diminta secara spesifik di prompt)\n"
        f"   - Coverage (Issues): '{default_coverage}' (Gunakan nilai ini untuk semua baris jika Coverage tidak diminta secara spesifik di prompt)\n"
        
        # PERUBAHAN UTAMA UNTUK FORMAT NAMA
        f"4. Name Format (STRICT): The Name column MUST STRICTLY follow the format: [Positive/Negative]-[{final_platform_tag}]-[{project_acronym_tag}][{action_tag}] - [Description]. "
        f"The platform tag MUST be '{final_platform_tag}' (which is dynamically determined by the user's selection). "
        f"The tag '{{project_acronym_tag}}' MUST be replaced by the acronym found in the documents (e.g., 'DPIA', 'RoPA', 'CISO', etc.) or derived from the prompt. "
        f"The tag '{{action_tag}}' MUST be replaced by the feature or menu action being tested. "
        f"The first character of the 'Name' column MUST be '[' (opening square bracket). \n"
        
        # INSTRUKSI KAPITALISASI (Revisi 1)
        "4a. Name Description Capitalization: The Description part (after the hyphen '-') MUST use a precise Title Case. Capitalize the first word and all major words (nouns, verbs, adjectives, adverbs), but KEEP all short prepositions (e.g., 'to', 'with', 'as', 'for', 'of'), articles ('a', 'an', 'the'), and conjunctions ('and', 'or', 'but') in **lowercase**, unless they are the first word. For example, 'Able to create RoPA as DPO Officer with all mandatory fields' must be formatted as: 'Able to Create RoPA as DPO Officer with All Mandatory Fields'. Maintain this capitalization style rigorously.\n"

        "4b. Name Punctuation: The description part in the 'Name' column MUST NOT end with a period (titik) atau any trailing punctuation.\n"
        
        "5. Test Type: This column MUST be either 'Positive' atau 'Negative', matching the Name prefix.\n"
        
        # INSTRUKSI KRUSIAL UNTUK MENCEGAH PERGESERAN KOLOM DAN HEADER GANDA (Revisi 2)
        "6. CSV Structure (STRICT QUOTING & SINGLE HEADER): Use double quotes (\") to enclose text for columns that might contain commas or newlines (specifically 'Precondition' and 'Test Script (BDD)'). This is crucial to prevent data from shifting columns in Excel/Sheets. The first line MUST be the header row. **DO NOT repeat the header row. The header MUST only appear once as the very first line.**"

        # INSTRUKSI UNTUK BDD MINIMAL DAN FOKUS PADA GIVEN/WHEN/THEN
        "7. Test Script (BDD) Format (MINIMAL): The 'Test Script (BDD)' column MUST ONLY contain the step definitions (Given, When, Then, And, But). DO NOT include the 'Scenario:' keyword. Each test case must be a single block of steps, starting with Given, followed by When, and ending with Then. Use And atau But to chain additional steps within the single block. The structure must be: ONE 'Given', ONE 'When', ONE 'Then'. The steps MUST be concise; DO NOT include long, specific valid data values (e.g., 'with document ID PB-1234-A-2025' or 'with name Budi and email budi@test.com'); abstract the data (e.g., 'with a valid document ID' or 'with valid user credentials'). Focus on the high-level action and outcome."
        
        "8. BDD Wording Consistency: All occurrences of the first-person pronoun 'I' (including 'I am', 'I want', 'I click', etc.) in the 'Test Script (BDD)' column MUST be replaced with the subject 'the user'. For example, 'Given I am logged in' becomes 'Given the user is logged in' or 'Given the user logs in'. Ensure all subsequent verbs are grammatically correct when using 'the user' (singular third person)."
        "9. RAW OUTPUT: The final output MUST be the raw CSV string and MUST NOT be enclosed within any Markdown code block delimiters (triple backticks, i.e., ```). The first character of the output MUST be the quote (\") or the first letter of the header column 'Name'. **DO NOT add any introductory text or explanation before or after the CSV.**"
       
        "\nAnalyze the provided documents and the user's Acceptance Criteria (AC) carefully to generate the necessary content for the Precondition, Objective, Labels, and Test Script (BDD), strictly adhering to all rules."
    )

    contents = files + [user_prompt]
    
    with st.spinner('AI sedang menganalisis dokumen dan menghasilkan Test Cases.....'):
        
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
            
            # Mengembalikan tag yang diekstrak (atau default)
            return response.text, start_time_str, duration_seconds, project_acronym_tag, action_tag
            
        except Exception as e:
            st.error(f"Gagal memanggil Gemini API: {e}") 
            return f"[ERROR] Gagal memanggil Gemini API: {e}", start_time_str, 0.0, "ERROR", "ERROR"

def delete_uploaded_files(client: genai.Client, files: list):
    """Menghapus file yang sudah diunggah dari server Gemini."""
    for file_obj in files:
        try:
            client.files.delete(name=file_obj.name)
        except Exception:
            pass 

# --- STREAMLIT INTERFACE ---

st.set_page_config(page_title="AuraTest (Zephyr-Gherkin)", layout="wide")

# Inisialisasi session state
if 'is_generating' not in st.session_state:
    st.session_state['is_generating'] = False
if 'csv_result' not in st.session_state:
    st.session_state['csv_result'] = None
if 'metadata' not in st.session_state:
    st.session_state['metadata'] = {}
# PERUBAHAN INTERFACE DI SINI: Default platform_tag sekarang "Website"
if 'platform_tag' not in st.session_state:
    st.session_state['platform_tag'] = "Website"
if 'user_prompt_content' not in st.session_state:
    st.session_state['user_prompt_content'] = ""
if 'project_tag' not in st.session_state:
    st.session_state['project_tag'] = ""
if 'action_tag' not in st.session_state:
    st.session_state['action_tag'] = ""
if 'api_key_input' not in st.session_state:
    st.session_state['api_key_input'] = os.getenv("GEMINI_API_KEY", "")
# STATE BARU UNTUK INPUT COVERAGE DAN LABELS
if 'default_coverage' not in st.session_state:
    st.session_state['default_coverage'] = DEFAULT_COVERAGE
if 'default_labels' not in st.session_state:
    st.session_state['default_labels'] = DEFAULT_LABELS

# Tambahkan state baru untuk melacak interaksi API Key
if 'api_key_interacted' not in st.session_state:
    st.session_state['api_key_interacted'] = bool(st.session_state['api_key_input']) 

# --- LOGIKA INISIALISASI VALIDASI API KEY DENGAN REVISI ---
if 'api_key_valid' not in st.session_state:
    initial_key = st.session_state['api_key_input']
    if initial_key:
        client = get_gemini_client(initial_key)
        st.session_state['api_key_valid'] = (client != "INVALID_KEY" and client is not None)
        if st.session_state['api_key_valid']:
            st.session_state['api_key_error_message'] = "API key valid!"
        else:
            st.session_state['api_key_error_message'] = "API key tidak valid!"
    else:
        st.session_state['api_key_valid'] = False
        st.session_state['api_key_error_message'] = None # PENTING: Hapus pesan di awal jika kosong
# --- AKHIR LOGIKA INISIALISASI VALIDASI API KEY DENGAN REVISI ---


# --- LOGIKA VALIDASI ---

# Tentukan status disabled total
is_disabled_on_process_or_result = (st.session_state.is_generating or st.session_state.csv_result is not None)

# Tentukan status disabled final untuk input selain API Key
# Disabled jika sedang proses/ada hasil ATAU jika API Key belum valid
final_disabled_state = is_disabled_on_process_or_result or (not st.session_state.api_key_valid)


# --- FUNGSI CALLBACK VALIDASI API KEY SAAT INPUT BERUBAH (MODIFIKASI) ---
def validate_api_key_on_change():
    # Set status interaksi menjadi True setelah callback dipanggil
    st.session_state['api_key_interacted'] = True 
    
    # Ambil nilai dari input_widget (sesuai key)
    current_key = st.session_state['api_key_input_widget'].strip()
    st.session_state['api_key_input'] = current_key
    st.session_state['api_key_valid'] = False
    st.session_state['api_key_error_message'] = None # Reset pesan

    if not current_key:
        # VALIDASI: API Key tidak boleh kosong
        st.session_state['api_key_error_message'] = "API key tidak boleh kosong!" 
        return # Menghentikan fungsi jika kosong
    
    # Clear cache client sebelum mencoba validasi
    get_gemini_client.clear()
    
    # Lakukan validasi
    client = get_gemini_client(current_key)
            
    if client == "INVALID_KEY":
        st.session_state['api_key_error_message'] = "API key tidak valid!"
    elif client:
        st.session_state['api_key_valid'] = True
        st.session_state['api_key_error_message'] = "API key valid! Input lainnya telah diaktifkan."
    else:
        # Fallback 
        st.session_state['api_key_error_message'] = "Validasi gagal. Coba lagi."
        
# --- END FUNGSI CALLBACK VALIDASI ---


# Sidebar untuk Konfigurasi Kunci API
st.sidebar.title("⚙️ Konfigurasi")

st.sidebar.subheader("🔑 API Key")

# Placeholder untuk menampilkan status validasi API Key di sidebar
api_key_status_placeholder = st.sidebar.empty()

# API KEY INPUT DENGAN on_change
api_key_input = st.sidebar.text_input(
    "Masukkan API key Anda:", 
    value=st.session_state['api_key_input'], 
    type="password",
    key='api_key_input_widget', 
    on_change=validate_api_key_on_change, # Memicu validasi saat input berubah (tekan Enter/klik luar)
    disabled=is_disabled_on_process_or_result 
)

# Menampilkan status API Key di sidebar: HANYA tampilkan jika sudah ada interaksi.
if st.session_state['api_key_interacted']: 
    if st.session_state['api_key_error_message']:
        if st.session_state['api_key_valid']:
            api_key_status_placeholder.success(f"✅ {st.session_state['api_key_error_message']}")
        else:
            api_key_status_placeholder.error(f"❌ {st.session_state['api_key_error_message']}")

# --- Wording dipindahkan di sini, di bawah API Key ---
st.sidebar.markdown("""
<small>Dapatkan kunci gratis di [Google AI Studio](https://aistudio.google.com/)</small>
""", unsafe_allow_html=True)
# ---------------------------------------------------

# Main App
st.title("AuraTest *(Zephyr-Gherkin)*")

# --- INFORMASI VALIDASI API KEY DI UTAMA ---
if not st.session_state.api_key_valid and not is_disabled_on_process_or_result:
    # Pesan umum muncul selama API key belum valid
    st.warning("⚠️ Mohon masukkan API key Anda di sidebar dan tekan Enter atau ngeklik di luar untuk mengaktifkan input dan tombol lainnya.")
# --- AKHIR INFORMASI VALIDASI API KEY ---

# --- PENAMBAHAN SELECT BOX UNTUK PLATFORM (DIPINDAHKAN KE SINI) ---
st.markdown("1. Pilih Target Platform")

platform_options = ["Website", "Back Office", "Android", "IOS", "API"]
selected_platform = st.selectbox(
    "", 
    options=platform_options, 
    index=platform_options.index(st.session_state['platform_tag']),
    disabled=final_disabled_state, 
    key='platform_selector'
)
st.session_state['platform_tag'] = selected_platform
# --- AKHIR SELECT BOX PLATFORM ---


# --- WIDGET FILE UPLOADER ---
st.markdown("---")
st.markdown("2. Unggah Dokumen Pendukung (PRD/Figma)")

# Placeholder untuk menampilkan error file uploader
file_uploader_error_placeholder = st.empty() 

# File Uploader
uploaded_files = st.file_uploader(
    "",
    type=['pdf', 'jpg', 'jpeg', 'png'],
    accept_multiple_files=True,
    disabled=final_disabled_state, 
    key='file_uploader_input'
)
# --- END FILE UPLOADER WIDGET ---

# Prompt Input
st.markdown("---")
st.markdown("3. Ketik/Tempelkan Detail Fungsionalitas yang akan Diuji")

# Placeholder untuk menampilkan error text area
prompt_error_placeholder = st.empty()

# Text Area
user_prompt = st.text_area(
    "",
    height=300,
    placeholder="Contoh:\nBuatkan test cases yang bisa dibuat dari dokumen tersebut dengan menggabungkannya. Baca semua text dari image dan juga text dari pdf nya. Test cases hanya untuk Notification for DPIA document saja dengan spesifik user DPO Officer & DPO Supervisor. Jika terdapat informasi mengenai backward compatibility buatkan juga test cases-nya.\n",
    key='user_prompt_input',
    value=st.session_state['user_prompt_content'], 
    disabled=final_disabled_state 
)
# Update session state setiap kali input berubah
st.session_state['user_prompt_content'] = user_prompt

# --- INPUT TEXT BARU UNTUK COVERAGE (ISSUES) DAN LABELS ---
st.markdown("---")
st.markdown("4. Metadata Tambahan (Opsional)")

col_labels, col_coverage = st.columns(2)

with col_labels:
    default_labels_input = st.text_input(
        "Labels", 
        placeholder="Contoh: qa-arief",
        key='default_labels_input_widget',
        value=st.session_state['default_labels'],
        disabled=final_disabled_state
    )
    st.session_state['default_labels'] = default_labels_input.strip()

with col_coverage:
    default_coverage_input = st.text_input(
        "Coverage (Issues) ID", 
        placeholder="Contoh: PB-1234",
        key='default_coverage_input_widget',
        value=st.session_state['default_coverage'],
        disabled=final_disabled_state
    )
    st.session_state['default_coverage'] = default_coverage_input.strip()
# --- AKHIR INPUT TEXT BARU ---


# Tombol Generate
st.markdown("---")

# Tombol Generate
if st.button("🚀 Generate Test Cases", type="primary", use_container_width=True, disabled=final_disabled_state):    
    
    # --- RESET HASIL LAMA SAAT TOMBOL INI DIKLIK ---
    st.session_state.csv_result = None
    st.session_state.metadata = {}
    st.session_state.project_tag = "" 
    st.session_state.action_tag = "" 
    
    # Reset error placeholders
    file_uploader_error_placeholder.empty()
    prompt_error_placeholder.empty()
    
    validation_errors = {}
    
    # 1. Validasi API Key (hanya cek status)
    if not st.session_state.api_key_valid:
        # Tampilkan error API Key secara mencolok di body utama juga
        st.error("❌ Validasi Gagal: Mohon masukkan dan validasi Kunci API Gemini di sidebar terlebih dahulu.")
        st.stop()
    
    # 2. Validasi Dokumen Pendukung
    if not uploaded_files:
        validation_errors['files'] = "Wajib Diisi"

    # 3. Validasi Prompt
    if not user_prompt.strip():
        validation_errors['prompt'] = "Wajib Diisi"
    
    # 4. Tampilkan pesan kesalahan jika ada
    if validation_errors:
        if 'files' in validation_errors:
            # Menggunakan placeholder untuk error file
            file_uploader_error_placeholder.error(validation_errors['files'])
        if 'prompt' in validation_errors:
            # Menggunakan placeholder untuk error prompt
            prompt_error_placeholder.error(validation_errors['prompt'])
        
        # Hentikan proses
        st.stop()
    
    # 5. Jika semua validasi lolos, lanjutkan
    st.session_state.is_generating = True 
    st.rerun() 


# --- Logika Eksekusi Proses Utama (hanya berjalan saat is_generating=True) ---
if st.session_state.is_generating:
    
    # Ambil client object (seharusnya dari cache dan sudah valid)
    client = get_gemini_client(st.session_state['api_key_input'])
    gemini_files = [] 
    
    # Cek ulang untuk safety, walaupun sudah divalidasi
    if client == "INVALID_KEY" or client is None:
        st.error("❌ Kesalahan internal: Kunci API terdeteksi tidak valid saat proses berjalan. Proses dihentikan.")
        st.session_state.is_generating = False
        st.rerun() 
    
    elif client:
        try:
            # 1. Upload Files
            gemini_files = upload_files_to_gemini(client, uploaded_files)
            
            # 2. Generate Test Case (KIRIMKAN NILAI COVERAGE DAN LABELS BARU)
            if gemini_files or not uploaded_files: 
                
                csv_result, start_time_str, duration_seconds, project_tag, action_tag = generate_test_cases_with_ai(
                    client, 
                    st.session_state['user_prompt_content'], # Gunakan versi dari state
                    gemini_files, 
                    st.session_state['platform_tag'],
                    st.session_state['default_labels'],     # Parameter Baru
                    st.session_state['default_coverage']    # Parameter Baru
                )
                
                if "[ERROR]" not in csv_result:
                    # Hitung jumlah test case dan tambahkan ke metadata
                    num_test_cases = count_csv_rows(csv_result)
                    
                    st.session_state.csv_result = csv_result
                    st.session_state.metadata = {
                        "start_time": start_time_str,
                        "duration": format_duration(duration_seconds),
                        "num_test_cases": num_test_cases 
                    }
                    # Simpan tag dalam huruf kecil
                    st.session_state.project_tag = project_tag.lower() 
                    st.session_state.action_tag = action_tag.lower() 
                else:
                    st.error("Gagal menghasilkan test cases. Lihat pesan error di atas.")
                
        except Exception as e:
            st.error(f"Terjadi kesalahan fatal selama proses: {e}")
        
        finally:
            # 4. Cleanup dan Reset Status
            delete_uploaded_files(client, gemini_files)
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
    | Jumlah Test Cases | `{metadata['num_test_cases']}` |
    | Waktu Mulai Generate | `{metadata['start_time']}` |
    | Durasi Proses | `{metadata['duration']}` |
    """, unsafe_allow_html=True)
    
    st.success("Yuhuuuuu, Test Cases berhasil dibuat")
    
    # PEMBUATAN NAMA FILE
    timestamp = datetime.datetime.now().strftime("_%Y%m%d_%H%M%S") 
    
    # DEFAULT TAGS (in lowercase, as stored in session state)
    DEFAULT_PROJECT = "dpia"
    DEFAULT_ACTION = "genericaction"
    
    # Cek apakah tag yang tersimpan adalah tag default atau ada error
    is_generic_or_error = (
        # Kondisi 1: Kedua tag adalah nilai default
        (st.session_state.project_tag == DEFAULT_PROJECT and st.session_state.action_tag == DEFAULT_ACTION) or 
        # Kondisi 2: Ada string "error" (jika terjadi API error saat generate)
        ("error" in st.session_state.project_tag) or
        # Kondisi 3: Salah satu atau kedua tag kosong/falsey
        (not st.session_state.project_tag or not st.session_state.action_tag)
    )
    
    if not is_generic_or_error:
        # Gunakan nama file spesifik jika tag terdeteksi dan bukan tag default
        base_file_name = f"{st.session_state.project_tag}_{st.session_state.action_tag}".lower()
        file_name_with_timestamp = f"{base_file_name}{timestamp}.csv"
    else:
        # Gunakan nama file default 'test_cases' jika generik atau ada error
        file_name_with_timestamp = f"test_cases{timestamp}.csv"
        
    st.info(f"Nama file yang akan diunduh: **{file_name_with_timestamp}**")
    
    # Menggunakan columns agar tombol download dan clear berdampingan
    col1, col2 = st.columns([1, 1])
    
    # Tombol Download di kolom pertama
    with col1:
        st.download_button(
            label="📥 Download Test Cases (CSV)",
            data=st.session_state.csv_result.encode('utf-8'),
            file_name=file_name_with_timestamp,
            mime="text/csv",
            use_container_width=True 
        )
    
    # Tombol Clear Output di kolom kedua
    with col2:
        if st.button("🗑️ Clear Output", type="secondary", use_container_width=True):
            # CUKUP HAPUS STATE YANG BERHUBUNGAN DENGAN HASIL DAN PROSES
            st.session_state.csv_result = None
            st.session_state.metadata = {}
            st.session_state.project_tag = ""
            st.session_state.action_tag = ""
            # JANGAN MENGUBAH api_key_input, api_key_valid, atau api_key_error_message
            st.rerun() 

    st.code(st.session_state.csv_result, language='csv')