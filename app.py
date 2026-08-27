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

# --- LOGIN AUTHENTICATION ---
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
                    st.error("Galat Username ya Password! (Username: admin, Password: admin)")
    st.stop()

# --- MAIN DASHBOARD ---
st.title("💎 Diamond OCR & Google Sheet Auto-Updater")
st.write("Upload slips and envelopes to extract diamond details and auto-update Google Sheet.")

# Helper to connect to Google Sheets
def get_google_sheet():
    try:
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive"
        ]
        gcp_info = dict(st.secrets["gcp_service_account"])
        creds = Credentials.from_service_account_info(gcp_info, scopes=scopes)
        client = gspread.authorize(creds)
        sheet_name = st.secrets.get("GOOGLE_SHEET_NAME", "Sheet1")
        return client.open(sheet_name).sheet1
    except Exception as e:
        st.error(f"Google Sheet Connection Error: {e}")
        return None

# AI OCR Processor
def process_images_with_gemini(images):
    try:
        api_key = st.secrets["GEMINI_API_KEY"]
        genai.configure(api_key=api_key)
        
        # Use latest recommended model
        model = genai.GenerativeModel("gemini-3.6-flash")
        
        prompt = """
        You are an expert OCR system for Diamond Manufacturing Slips and Envelopes.
        Extract data from the provided images and return a JSON list of records.
        For each diamond parcel, extract:
        - SrNo: Serial Number or Lot No from Pink Slip
        - ToColour: Diamond Color (e.g., D, E, F, G, WHITE, etc.)
        - ToClarity: Clarity grade (e.g., VVS1, VS1, SI1, etc.)
        - RecPices: Number of pieces received
        - RecTotalWt: Total weight / Carats received
        - RecDate: Date (DD/MM/YYYY or DD-MM-YYYY)
        - Actual_MM: Millimeter size if available
        - Actual_CertNo: Certificate number if available
        
        Return ONLY a valid JSON array like:
        [
          {
            "SrNo": "101",
            "ToColour": "WHITE",
            "ToClarity": "VVS1",
            "RecPices": "1",
            "RecTotalWt": "0.50",
            "RecDate": "28/08/2026",
            "Actual_MM": "5.10",
            "Actual_CertNo": "GIA123456"
          }
        ]
        """
        
        contents = [prompt]
        for img in images:
            contents.append(Image.open(img))
            
        response = model.generate_content(contents)
        text = response.text.strip()
        json_match = re.search(r'\[.*\]', text, re.DOTALL)
        if json_match:
            return json.loads(json_match.group(0))
        return []
    except Exception as e:
        st.error(f"AI Extraction Error: {e}")
        return []

# File Upload Section
uploaded_files = st.file_uploader(
    "Upload Diamond Images (Pink Slip / White Envelope)",
    type=["jpg", "jpeg", "png"],
    accept_multiple_files=True
)

if uploaded_files:
    st.info(f"📸 {len(uploaded_files)} images selected.")
    
    if st.button("🚀 Process & Update Google Sheet"):
        with st.spinner("Analyzing images and extracting diamond data..."):
            extracted_records = process_images_with_gemini(uploaded_files)
            
            if extracted_records:
                st.success("Data successfully extracted!")
                df = pd.DataFrame(extracted_records)
                st.dataframe(df)
                
                # Update Google Sheet
                sheet = get_google_sheet()
                if sheet:
                    try:
                        for rec in extracted_records:
                            row_vals = list(rec.values())
                            sheet.append_row(row_vals)
                        st.success("✅ Google Sheet updated successfully!")
                    except Exception as err:
                        st.error(f"Sheet write error: {err}")
            else:
                st.warning("No clear data could be extracted. Please check the image quality.")
