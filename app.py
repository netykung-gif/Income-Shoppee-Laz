import streamlit as st
import pandas as pd
import pdfplumber
import re
import io

# --- 1. ฟังก์ชันตั้งต้น (จากโค้ดรายได้) ---
PUA_MAP = {"\uf70a": "\u0e48", "\uf70b": "\u0e49", "\uf70e": "\u0e4c"}
def fix_thai(s):
    if not s: return s
    for bad, good in PUA_MAP.items(): s = s.replace(bad, good)
    return s

# --- 2. ฟังก์ชันดึงค่าใช้จ่าย Shopee (รวม Logic ใหม่) ---
def get_shopee_expense_data(file):
    data_list = []
    with pdfplumber.open(file) as pdf:
        for idx, page in enumerate(pdf.pages):
            text = page.extract_text() or ""
            lines = [line.strip() for line in text.split('\n') if line.strip()]
            shopee = "Shopee" in text or "Receipt/Tax Invoice" in text
            spx = "SPX Express" in text or ("Receipt" in text and not shopee)
            doc_no, doc_date, total_amount = "Unknown", "Unknown", "0.0"
            for i, line in enumerate(lines):
                if ("เลขที่" in line or "No." in line) and re.search(r"[A-Z]{3,}", line):
                    match = re.search(r"([A-Z0-9\-]{10,})", line)
                    if match: doc_no = match.group(1)
                if "วันที่" in line or "Date" in line:
                    date_match = re.search(r"(\d{2}/\d{2}/\d{4})", line)
                    if date_match: doc_date = date_match.group(1)
            total_match = re.search(r"Total(?: amount| Value of Services)?.*?\s*([\d,]+\.\d{2})", text, re.IGNORECASE)
            if total_match: total_amount = total_match.group(1).replace(",", "")
            data_list.append({"Page": idx+1, "Company": "Shopee/SPX", "Doc No.": doc_no, "Date": doc_date, "Total": float(total_amount)})
    return pd.DataFrame(data_list)

# --- 3. ฟังก์ชันดึงค่าใช้จ่าย Lazada (รวม Logic ใหม่) ---
def get_lazada_expense_data(file):
    rows = []
    with pdfplumber.open(file) as pdf:
        for idx, page in enumerate(pdf.pages):
            text = page.extract_text() or ""
            for line in text.split("\n"):
                m = re.match(r"^(\d{2}/\d{2}/\d{4})\s+(.+?)\s+([\d,]+\.\d{2})", line.strip())
                if m:
                    date, desc, amount = m.groups()
                    rows.append({"Page": idx+1, "Date": date, "Desc": desc, "Total": float(amount.replace(",", ""))})
    return pd.DataFrame(rows)

# --- 4. หน้า UI หลัก (รวมทุกอย่าง) ---
st.title("📊 ระบบสรุปข้อมูล Shopee & Lazada")

# แท็บแยกตามหน้าที่
tab1, tab2, tab3, tab4 = st.tabs(["รายได้ Shopee", "รายได้ Lazada", "ค่าใช้จ่าย Shopee", "ค่าใช้จ่าย Lazada"])

# --- แท็บ 1 & 2: รายได้ (วางโค้ดดึงรายได้เดิมของคุณ) ---
with tab1:
    st.write("ระบบดึงรายได้ Shopee")
    # วาง Logic ดึงรายได้เดิมของคุณที่นี่...

with tab2:
    st.write("ระบบดึงรายได้ Lazada")
    # วาง Logic ดึงรายได้เดิมของคุณที่นี่...

# --- แท็บ 3: ค่าใช้จ่าย Shopee ---
with tab3:
    f = st.file_uploader("อัปโหลด PDF ค่าใช้จ่าย Shopee", type=["pdf"], key="exp_sh")
    if f:
        df = get_shopee_expense_data(f)
        st.dataframe(df)
        buf = io.BytesIO()
        df.to_excel(buf, index=False)
        st.download_button("📥 โหลด Excel Shopee", buf.getvalue(), "Shopee_Expense.xlsx")

# --- แท็บ 4: ค่าใช้จ่าย Lazada ---
with tab4:
    f = st.file_uploader("อัปโหลด PDF ค่าใช้จ่าย Lazada", type=["pdf"], key="exp_lz")
    if f:
        df = get_lazada_expense_data(f)
        st.dataframe(df)
        buf = io.BytesIO()
        df.to_excel(buf, index=False)
        st.download_button("📥 โหลด Excel Lazada", buf.getvalue(), "Lazada_Expense.xlsx")
