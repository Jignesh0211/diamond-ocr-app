import streamlit as st
import pandas as pd
import json
import os
import io
import re
from datetime import datetime
from zoneinfo import ZoneInfo
from PIL import Image, ImageEnhance, ImageFilter
import gspread
from google.oauth2.service_account import Credentials
import google.generativeai as genai

# Page Config
st.set_page_config(page_title="Diamond OCR & Google Sheet", layout="wide", page_icon="💎")

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
                if username.strip().lower() == "admin" and password.strip().lower() == "admin":
                    st.session_state.authenticated = True
                    st.rerun()
                else:
                    st.error("Galat Username ya Password! (admin / admin)")
    st.stop()

st.title("💎 Diamond OCR Auto-Updater (High-Res Bulk Mode)")

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
        sheet_name = st.secrets.get("GOOGLE_SHEET_NAME", "DD sheet").strip()
        spreadsheet = client.open(sheet_name)
        return spreadsheet.sheet1
    except Exception as e:
        st.error(f"Google Sheet Connection Error: {str(e)}")
        return None

# High-Resolution Image Preprocessor
def enhance_image_for_ocr(uploaded_file):
    image = Image.open(uploaded_file)
    if image.mode != "RGB":
        image = image.convert("RGB")
    
    # Increase contrast and sharpness for fine text clarity
    enhancer_contrast = ImageEnhance.Contrast(image)
    image = enhancer_contrast.enhance(1.4)
    
    enhancer_sharpness = ImageEnhance.Sharpness(image)
    image = enhancer_sharpness.enhance(1.5)
    
    return image

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

# High-Precision Bulk OCR Processor
def process_bulk_images_with_gemini(images):
    try:
        api_key = st.secrets["GEMINI_API_KEY"].strip()
        genai.configure(api_key=api_key)
        
        generation_config = {
            "temperature": 0.0,
            "top_p": 1.0
        }
        
        model = genai.GenerativeModel(
            model_name="gemini-3.6-flash",
            generation_config=generation_config
        )
        
        prompt = """
        You are a FORENSIC-GRADE OCR SCANNER for Diamond Grading Lab Reports (IGI, GIA) and Factory Pink Slips.
        
        MANDATORY VERIFICATION PROTOCOL FOR CERTIFICATE NUMBERS:
        1. Zoom in mentally on the Certificate Number / Report Number section.
        2. Perform character-by-character spell-out verification.
        3. Differentiate loops strictly:
           - '8': Has TWO full, closed, symmetric loops (top loop AND bottom loop).
           - '6': Has only ONE bottom loop with an open, curving top stem.
           - '0': Single large hollow oval.
           - 'B': Flat left vertical line with two right curves.
        4. If a digit looks like an 8 (two circles), DO NOT convert it to a 6.

        DATA MAPPING RULES:
        - Pink Slip: Extract 'SrNo' (Serial/Lot No) and 'RecPices'.
        - Lab Certificate: Extract Carat Weight ('RecTotalWt'), Measurements ('Actual MM'), Colour ('ToColour'), Clarity ('ToClarity'), and exact Certificate Number ('Actual CertNo').
        - Match each Pink Slip with its respective Lab Certificate.

        Return ONLY a JSON array of objects with the exact schema:
        [
          {
            "SrNo": "770306",
            "ToColour": "D",
            "ToClarity": "VVS2",
            "RecPices": "1",
            "RecTotalWt": "1.00",
            "Actual MM": "6.41 - 6.47 X 3.96",
            "Actual CertNo": "LG816614805"
          }
        ]
        """
        
        enhanced_images = [enhance_image_for_ocr(img) for img in images]
        contents = [prompt] + enhanced_images
        
        response = model.generate_content(contents)
        json_match = re.search(r'\[.*\]', response.text.strip(), re.DOTALL)
        
        if json_match:
            records = json.loads(json_match.group(0))
            
            try:
                upload_date = datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%d-%b-%y")
            except Exception:
                upload_date = datetime.now().strftime("%d-%b-%y")
            
            cleaned_records = []
            for r in records:
                r["RecDate"] = upload_date
                r["RecTotalWt"] = format_weight(r.get("RecTotalWt", ""))
                r["Actual MM"] = format_mm(r.get("Actual MM", ""))
                r["Actual CertNo"] = format_cert_no(r.get("Actual CertNo", ""))
                cleaned_records.append(r)
            return cleaned_records
        return []
    except Exception as e:
        st.error(f"AI Extraction Error: {e}")
        return []

# Sheet Update Logic by SrNo
def update_sheet_by_srno(sheet, records):
    headers = sheet.row_values(1)
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
    updated_count = 0
    
    for rec in records:
        target_sr = str(rec.get("SrNo", "")).strip()
        if not target_sr or target_sr.lower() == "none":
            continue
        
        if target_sr in all_srnos:
            row_idx = all_srnos.index(target_sr) + 1
            for field, col_idx in field_map.items():
                if col_idx and field in rec and str(rec[field]).strip() not in ["None", ""]:
                    sheet.update_cell(row_idx, col_idx, str(rec[field]))
            updated_count += 1
            
    return True, f"Successfully {updated_count} diamond parcel(s) matched and updated in Google Sheet!"

# File Upload Section (Bulk)
uploaded_files = st.file_uploader(
    "Upload All Diamond Images Together (Slips & Certificates)",
    type=["jpg", "jpeg", "png"],
    accept_multiple_files=True
)

if uploaded_files:
    st.info(f"📸 {len(uploaded_files)} images loaded for Enhanced OCR.")
    
    if st.button("🚀 Process & Update Google Sheet Directly"):
        with st.spinner(f"Enhancing contrast and processing {len(uploaded_files)} images with forensic OCR..."):
            extracted_records = process_bulk_images_with_gemini(uploaded_files)
            
            if extracted_records:
                st.write("### 📊 Extracted Summary:")
                st.dataframe(pd.DataFrame(extracted_records), use_container_width=True)
                
                sheet = get_google_sheet()
                if sheet is not None:
                    success, msg = update_sheet_by_srno(sheet, extracted_records)
                    if success:
                        st.success(f"✅ {msg}")
                    else:
                        st.error(f"❌ {msg}")
            else:
                st.warning("Could not extract valid diamond records. Please ensure images are clear.")
