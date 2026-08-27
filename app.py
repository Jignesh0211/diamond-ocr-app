import streamlit as st
import pandas as pd
import json
import os
import io
import re
from datetime import datetime
from PIL import Image
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

st.title("💎 Diamond OCR & Google Sheet Auto-Updater")

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
    s = str(raw_cert).strip()
    if not s.upper().startswith("IGI"):
        s = f"IGI {s}"
    return s

def format_weight(raw_wt):
    if not raw_wt or str(raw_wt).strip().lower() in ["none", ""]:
        return ""
    # Extract numeric float part (e.g. '1.00 CARAT' -> '1.00')
    match = re.search(r'\d+(\.\d+)?', str(raw_wt))
    return match.group(0) if match else str(raw_wt).strip()

# AI OCR Processor
def process_images_with_gemini(images):
    try:
        api_key = st.secrets["GEMINI_API_KEY"].strip()
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel("gemini-3.6-flash")
        
        prompt = """
        Extract diamond parcel details from all provided images:
        - SrNo: Serial Number / Lot No from Pink slip (e.g., 770306)
        - ToColour: Diamond Colour (e.g., D, E, F)
        - ToClarity: Diamond Clarity (e.g., VVS1, VVS2)
        - RecPices: Received pieces (e.g., 1)
        - RecTotalWt: Carat weight directly from the Grading Certificate (e.g., 1.00 or 1.50)
        - Actual MM: Measurement numbers (e.g., 6.41 - 6.47 X 3.96)
        - Actual CertNo: Certificate number (e.g., LG616614805)
        
        Prioritize the Certificate for weight (RecTotalWt), measurements (Actual MM), colour, clarity, and cert number.
        Merge information for the matching diamond parcel.
        Return strictly a JSON array of objects.
        """
        contents = [prompt] + [Image.open(img) for img in images]
        response = model.generate_content(contents)
        json_match = re.search(r'\[.*\]', response.text.strip(), re.DOTALL)
        
        if json_match:
            records = json.loads(json_match.group(0))
            upload_date = datetime.now().strftime("%d-%b-%y") # Current upload date: e.g. 28-Aug-26
            
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
            
    return True, f"Successfully {updated_count} record(s) matched and updated in their respective rows!"

# File Upload Section
uploaded_files = st.file_uploader("Upload Diamond Images", type=["jpg", "jpeg", "png"], accept_multiple_files=True)

if uploaded_files:
    st.info(f"📸 {len(uploaded_files)} images selected.")
    if st.button("🚀 Process & Update Google Sheet"):
        with st.spinner("Extracting certificate details and updating row..."):
            extracted_records = process_images_with_gemini(uploaded_files)
            if extracted_records:
                st.success("Data successfully formatted & extracted!")
                st.dataframe(pd.DataFrame(extracted_records))
                
                sheet = get_google_sheet()
                if sheet is not None:
                    success, msg = update_sheet_by_srno(sheet, extracted_records)
                    if success:
                        st.success(f"✅ {msg}")
                    else:
                        st.error(f"❌ {msg}")
            else:
                st.warning("No clear data could be extracted.")
