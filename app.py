import streamlit as st
import pandas as pd
import json
import os
import io
import re
from datetime import datetime
from zoneinfo import ZoneInfo
from PIL import Image, ImageEnhance
import gspread
from google.oauth2.service_account import Credentials
import google.generativeai as genai
from concurrent.futures import ThreadPoolExecutor

# Page Config
st.set_page_config(page_title="Diamond OCR Ultra-Fast", layout="wide", page_icon="💎")

# Login Authentication
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False

if not st.session_state.authenticated:
    st.markdown("<h2 style='text-align: center;'>🔒 Login to Diamond OCR Software</h2>", unsafe_allow_html=True)
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        with st.form("login_form"):
            username = st.text_input("Username")
            password = st.text_input("Password", type="password")
            submit = st.form_submit_button("Login")
            if submit:
                if username.strip().lower() == "jignesh" and password.strip() == "0211":
                    st.session_state.authenticated = True
                    st.rerun()
                else:
                    st.error("Galat Username ya Password!")
    st.stop()

st.title("⚡ Diamond OCR Ultra-Fast Bulk Updater")

# Google Sheet Connector
def get_google_sheet():
    try:
        scopes = [
            "https://spreadsheets.google.com/feeds",
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive"
        ]
        if "GCP_JSON" in st.secrets:
            gcp_info = json.loads(st.secrets["GCP_JSON"].strip())
        elif "gcp_service_account" in st.secrets:
            gcp_info = dict(st.secrets["gcp_service_account"])
        else:
            st.error("Secrets me Service Account details nahi mili!")
            return None
            
        creds = Credentials.from_service_account_info(gcp_info, scopes=scopes)
        client = gspread.authorize(creds)
        sheet_name = st.secrets.get("GOOGLE_SHEET_NAME", "Dimond Demand Sheet").strip()
        spreadsheet = client.open(sheet_name)
        return spreadsheet.sheet1
    except Exception as e:
        st.error(f"Google Sheet Connection Error: {str(e)}")
        return None

# Fast Image Optimization
def fast_optimize_image(uploaded_file):
    img = Image.open(uploaded_file)
    if img.mode != "RGB":
        img = img.convert("RGB")
    
    max_dim = 1400
    if max(img.size) > max_dim:
        img.thumbnail((max_dim, max_dim), Image.Resampling.LANCZOS)
        
    enhancer = ImageEnhance.Contrast(img)
    return enhancer.enhance(1.3)

# Formatting Helpers
def format_mm(raw_mm):
    if not raw_mm or str(raw_mm).strip().lower() in ["none", ""]:
        return ""
    s = re.sub(r'(?i)mm', '', str(raw_mm)).strip()
    s = re.sub(r'[\s\-xX]+', '*', s)
    s = re.sub(r'\*+', '*', s).strip('*')
    return s

def format_cert_no(raw_cert):
    if not raw_cert or str(raw_cert).strip().lower() in ["none", ""]:
        return ""
    s = str(raw_cert).strip().replace(" ", "").upper()
    if not s.startswith("IGI"):
        s = f"IGI {s}"
    else:
        s = f"IGI {s[3:]}"
    return s

def format_weight(raw_wt):
    if not raw_wt or str(raw_wt).strip().lower() in ["none", ""]:
        return ""
    match = re.search(r'\d+(\.\d+)?', str(raw_wt))
    return match.group(0) if match else str(raw_wt).strip()

# Single Batch AI Extraction
def process_batch_ai(batch_images, model):
    prompt = """
    Extract diamond parcel data from images as JSON array:
    - SrNo: Serial Number from Pink Slip
    - ToColour: Diamond Colour
    - ToClarity: Diamond Clarity
    - RecPices: Received pieces
    - RecTotalWt: Carat weight from Certificate
    - Actual MM: Dimensions/Measurements
    - Actual CertNo: Exact certificate number
    
    Return strictly JSON:
    [{"SrNo": "770306", "ToColour": "D", "ToClarity": "VVS2", "RecPices": "1", "RecTotalWt": "1.00", "Actual MM": "6.41*6.47*3.96", "Actual CertNo": "LG816614805"}]
    """
    try:
        contents = [prompt] + batch_images
        response = model.generate_content(contents)
        json_match = re.search(r'\[.*\]', response.text.strip(), re.DOTALL)
        if json_match:
            return json.loads(json_match.group(0))
    except Exception as e:
        st.error(f"Batch AI Error: {e}")
    return []

# Sheet Batch Update Logic with Light Blue Highlighting
def fast_batch_update_sheet(sheet, records):
    headers = sheet.row_values(1)
    num_cols = len(headers)
    clean_headers = [re.sub(r'[^a-zA-Z0-9]', '', h).lower() for h in headers]
    
    def find_col(name_patterns):
        for pattern in name_patterns:
            clean_pat = re.sub(r'[^a-zA-Z0-9]', '', pattern).lower()
            if clean_pat in clean_headers:
                return clean_headers.index(clean_pat) + 1
        return None

    srno_col = find_col(["SrNo", "Sr No", "SerialNo"])
    if not srno_col:
        return False, "Sheet me 'SrNo' column nahi mila!"

    field_map = {
        "ToColour": find_col(["ToColour", "ToColor", "Color", "Colour"]),
        "ToClarity": find_col(["ToClarity", "Clarity"]),
        "RecPices": find_col(["RecPices", "RecPcs", "Pcs", "Rec Pcs"]),
        "RecTotalWt": find_col(["RecTotalWt", "RecWt", "Rec Total Wt", "Weight"]),
        "RecDate": find_col(["RecDate", "Rec Date"]),
        "Actual MM": find_col(["Actual MM", "ActualMM", "MM", "Size"]),
        "Actual CertNo": find_col(["Actual CertNo", "ActualCertNo", "CertNo", "CertificateNo"])
    }

    all_srnos = [str(x).strip() for x in sheet.col_values(srno_col)]
    updates = []
    matched_rows = []
    
    for rec in records:
        target_sr = str(rec.get("SrNo", "")).strip()
        if not target_sr or target_sr.lower() == "none":
            continue
        
        if target_sr in all_srnos:
            row_idx = all_srnos.index(target_sr) + 1
            matched_rows.append(row_idx)
            for field, col_idx in field_map.items():
                if col_idx and field in rec and str(rec[field]).strip() not in ["None", ""]:
                    updates.append({
                        'range': gspread.utils.rowcol_to_a1(row_idx, col_idx),
                        'values': [[str(rec[field])]]
                    })
    
    if updates:
        # Step A: Data Update
        sheet.batch_update(updates)
        
        # Step B: Highlight Row with Light Blue (#D9EAD3 / #CFE2F3)
        light_blue_color = {"red": 0.81, "green": 0.88, "blue": 0.95} # Soft Light Blue
        for r_idx in matched_rows:
            try:
                sheet.format(
                    f"A{r_idx}:{gspread.utils.rowcol_to_a1(r_idx, max(num_cols, 26))}",
                    {"backgroundColor": light_blue_color}
                )
            except Exception as fe:
                pass
                
        return True, f"Successfully {len(matched_rows)} row(s) updated and highlighted in Light Blue!"
    return False, "Koi matching SrNo nahi mila."

# Bulk Uploader UI
uploaded_files = st.file_uploader(
    "Upload Bulk Diamond Images",
    type=["jpg", "jpeg", "png"],
    accept_multiple_files=True
)

if uploaded_files:
    st.info(f"⚡ {len(uploaded_files)} images queued for high-speed processing.")
    
    if st.button("🚀 Fast Process & Update Google Sheet"):
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        status_text.text("⚡ Optimizing images in parallel...")
        with ThreadPoolExecutor() as executor:
            optimized_images = list(executor.map(fast_optimize_image, uploaded_files))
        
        progress_bar.progress(30)
        status_text.text("⚡ Processing AI OCR...")
        
        api_key = st.secrets["GEMINI_API_KEY"].strip()
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel("gemini-3.6-flash", generation_config={"temperature": 0.0})
        
        chunk_size = 6
        all_extracted = []
        for i in range(0, len(optimized_images), chunk_size):
            chunk = optimized_images[i:i + chunk_size]
            records = process_batch_ai(chunk, model)
            all_extracted.extend(records)
            
        progress_bar.progress(70)
        
        if all_extracted:
            status_text.text("⚡ Formatting and highlighting Google Sheet...")
            try:
                upload_date = datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%d-%b-%y")
            except Exception:
                upload_date = datetime.now().strftime("%d-%b-%y")
                
            cleaned_records = []
            for r in all_extracted:
                r["RecDate"] = upload_date
                r["RecTotalWt"] = format_weight(r.get("RecTotalWt", ""))
                r["Actual MM"] = format_mm(r.get("Actual MM", ""))
                r["Actual CertNo"] = format_cert_no(r.get("Actual CertNo", ""))
                cleaned_records.append(r)
            
            sheet = get_google_sheet()
            if sheet is not None:
                success, msg = fast_batch_update_sheet(sheet, cleaned_records)
                progress_bar.progress(100)
                if success:
                    st.success(f"✅ {msg}")
                    st.dataframe(pd.DataFrame(cleaned_records), use_container_width=True)
                else:
                    st.error(f"❌ {msg}")
        else:
            progress_bar.progress(100)
            st.warning("No data extracted from images.")
