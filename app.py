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

# Login Bypass
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
        sheet_name = st.secrets.get("GOOGLE_SHEET_NAME", "Sheet1").strip()
        
        # Open by title
        spreadsheet = client.open(sheet_name)
        return spreadsheet.sheet1
    except Exception as e:
        st.error(f"Google Sheet Connection Error: {str(e)}")
        return None

# AI OCR Processor
def process_images_with_gemini(images):
    try:
        api_key = st.secrets["GEMINI_API_KEY"].strip()
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel("gemini-3.6-flash")
        
        prompt = """
        Extract diamond parcel details from images in valid JSON list:
        - SrNo: Serial Number or Lot No
        - ToColour: Diamond Color
        - ToClarity: Clarity grade
        - RecPices: Number of pieces
        - RecTotalWt: Weight in carats
        - RecDate: Date (DD/MM/YYYY)
        - Actual_MM: Measurement in mm
        - Actual_CertNo: Certificate number
        Return ONLY a JSON array.
        """
        contents = [prompt] + [Image.open(img) for img in images]
        response = model.generate_content(contents)
        json_match = re.search(r'\[.*\]', response.text.strip(), re.DOTALL)
        if json_match:
            return json.loads(json_match.group(0))
        return []
    except Exception as e:
        st.error(f"AI Extraction Error: {e}")
        return []

# File Upload Section
uploaded_files = st.file_uploader("Upload Diamond Images", type=["jpg", "jpeg", "png"], accept_multiple_files=True)

if uploaded_files:
    st.info(f"📸 {len(uploaded_files)} images selected.")
    if st.button("🚀 Process & Update Google Sheet"):
        with st.spinner("Analyzing images and extracting diamond data..."):
            extracted_records = process_images_with_gemini(uploaded_files)
            if extracted_records:
                st.success("Data successfully extracted!")
                st.dataframe(pd.DataFrame(extracted_records))
                
                sheet = get_google_sheet()
                if sheet is not None:
                    try:
                        for rec in extracted_records:
                            # Replace None with empty string for clean sheet insertion
                            clean_vals = ["" if v is None else str(v) for v in rec.values()]
                            sheet.append_row(clean_vals)
                        st.success("✅ Google Sheet updated successfully!")
                    except Exception as err:
                        st.error(f"Sheet write error: {err}")
            else:
                st.warning("No clear data could be extracted.")
