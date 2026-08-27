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

# --- LOGIN BYPASS / AUTHENTICATION ---
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
                # Direct admin / admin se login ho jayega bina error ke
                if username.strip().lower() == "admin" and password.strip().lower() == "admin":
                    st.session_state.authenticated = True
                    st.rerun()
                else:
                    st.error("Galat Username ya Password! (Username: admin, Password: admin)")
    st.stop()

# --- MAIN DASHBOARD ---
st.title("💎 Diamond OCR Auto-Updater")
st.write("Welcome, **Admin**! Upload your slip/envelope images below.")

uploaded_files = st.file_uploader("Upload Diamond Images (Pink Slip / White Envelope)", type=["jpg", "jpeg", "png"], accept_multiple_files=True)

if uploaded_files:
    st.success(f"{len(uploaded_files)} files uploaded successfully!")
