import os
import sys
import datetime
from google import genai
from google.genai import types

# Definisikan nama file output CSV
OUTPUT_FILENAME = f"test_cases_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"

def upload_files_to_gemini(client: genai.Client, file_paths: list) -> list:
    """Mengunggah file lokal ke Gemini API dan mengembalikan list file objects."""
    uploaded_files = []
    print("\n--- Memulai Proses Upload File ---")
    for path in file_paths:
        if not os.path.exists(path):
            print(f"  [SKIPPED] File tidak ditemukan di jalur: {path}")
            continue
            
        try:
            print(f"Mengunggah file: {os.path.basename(path)}...")
            file_obj = client.files.upload(file=path)
            uploaded_files.append(file_obj)
            print(f"  [SUKSES] File '{file_obj.display_name}' terunggah. Tipe: {file_obj.mime_type}")
        except Exception as e:
            print(f"  [GAGAL] Mengunggah {os.path.basename(path)}: {e}")
            
    if not uploaded_files and file_paths:
        print("\n[Peringatan]: Tidak ada file yang berhasil diunggah. Output hanya akan bergantung pada prompt.")
        
    return uploaded_files

def generate_test_cases_with_ai(client: genai.Client, user_prompt: str, files: list) -> str:
    """Memanggil Gemini API untuk menghasilkan test case dalam format CSV."""
    
    # SYSTEM INSTRUCTION BARU: Meminta output dalam format CSV
    system_instruction = (
        "You are an expert QA Engineer specialized in generating structured test cases. "
        "Your task is to generate test cases in the exact following CSV format: "
        "Name,Status,Precondition,Objective,Estimated Time,Labels,Coverage (Issues),Automation,Test Type,Test Script (BDD). "
        "The first line MUST be the header row. All text, including the BDD Gherkin steps, MUST be in English. "
        "Base your output strictly on the provided documents and the user's Acceptance Criteria (AC). "
        "Use double quotes (\") to enclose text containing commas or newlines (such as the Test Script). "
        "Do not include any introductory or explanatory text outside of the raw CSV content."
    )

    # Isi konten untuk dikirim ke API
    contents = files + [user_prompt]
    
    print("\n--- Memanggil Gemini AI untuk Generate Test Case (Output CSV) ---")
    try:
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                temperature=0.2 
            )
        )
        print("[SUKSES] Generasi selesai.")
        return response.text
    except Exception as e:
        return f"\n[ERROR API]: Gagal memanggil Gemini API. Pastikan kunci API Anda benar dan memiliki akses. Detail: {e}"

def save_output_to_csv(csv_content: str):
    """Menyimpan konten string CSV ke dalam file."""
    try:
        with open(OUTPUT_FILENAME, 'w', encoding='utf-8') as f:
            f.write(csv_content)
        print(f"\n[SUKSES] Data Test Case berhasil disimpan ke file: {OUTPUT_FILENAME}")
    except Exception as e:
        print(f"\n[ERROR] Gagal menyimpan file CSV: {e}")

def delete_uploaded_files(client: genai.Client, files: list):
    """Menghapus file yang sudah diunggah dari server untuk cleanup."""
    print("\n--- Membersihkan (Menghapus) File yang Diunggah ---")
    for file_obj in files:
        try:
            client.files.delete(name=file_obj.name)
            print(f"  [HAPUS] File {file_obj.display_name} berhasil dihapus.")
        except Exception as e:
            print(f"  [GAGAL HAPUS] File {file_obj.display_name}: {e}. Anda mungkin perlu menghapus manual.")

def main():
    # --- INISIASI & INPUT KUNCI API ---
    api_key = input("Masukkan Kunci API Gemini Anda (GEMINI_API_KEY): ")
    if not api_key:
        print("\n[ERROR] Kunci API tidak boleh kosong.")
        sys.exit(1)
        
    try:
        client = genai.Client(api_key=api_key)
    except Exception as e:
        print(f"\n[ERROR] Gagal inisiasi client API: {e}")
        sys.exit(1)

    # --- INPUT FILE ---
    print("\nMasukkan jalur (path) file yang ingin dianalisis (misalnya: 'dokumen.pdf, mockup.jpg').")
    print("Pisahkan dengan koma. File harus berada di folder yang sama atau gunakan path lengkap.")
    file_paths_input = input("Jalur File (Path): ")
    
    if file_paths_input:
        file_paths = [p.strip() for p in file_paths_input.split(',') if p.strip()]
    else:
        file_paths = []
        
    # --- INPUT PROMPT UTAMA ---
    print("\nMasukkan Prompt Anda (termasuk AC dan detail format test case).")
    print("Tekan Enter dua kali (baris kosong) saat selesai:")
    lines = []
    while True:
        try:
            line = input()
            if not line:
                break
            lines.append(line)
        except EOFError: 
            break
            
    user_prompt = "\n".join(lines)

    if not user_prompt.strip():
        print("\n[ERROR] Prompt tidak boleh kosong.")
        sys.exit(1)

    # 1. Upload File
    uploaded_files = upload_files_to_gemini(client, file_paths)
    
    # 2. Generate Test Case
    result_csv = generate_test_cases_with_ai(client, user_prompt, uploaded_files)
    
    # 3. Output Hasil dan Simpan ke CSV
    print("\n========================================================")
    print("               HASIL GENERASI TEST CASE                 ")
    print("========================================================")
    print(result_csv)
    print("========================================================")
    
    if "[ERROR API]" not in result_csv:
        save_output_to_csv(result_csv)
    
    # 4. Cleanup
    delete_uploaded_files(client, uploaded_files)

if __name__ == "__main__":
    main()