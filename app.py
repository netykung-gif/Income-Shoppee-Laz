import streamlit as st
import pandas as pd
import pdfplumber
import re
import io

# --- 1. ฟังก์ชันดึงข้อมูล Shopee ---
def get_shopee_expense_data(file):
    data_list = []
    with pdfplumber.open(file) as pdf:
        for idx, page in enumerate(pdf.pages):
            text = page.extract_text() or ""
            if not text: continue
            lines = [line.strip() for line in text.split('\n') if line.strip()]
            
            shopee = "Shopee" in text or "Receipt/Tax Invoice" in text
            spx = "SPX Express" in text or ("Receipt" in text and not shopee)
            
            doc_no, doc_date, total_amount = "Unknown", "Unknown", "Unknown"
            
            for i, line in enumerate(lines):
                if ("เลขที่" in line or "No." in line) and re.search(r"[A-Z]{3,}", line):
                    top_match = re.search(r"([A-Z0-9\-]{10,})", line)
                    if top_match:
                        doc_no = top_match.group(1)
                        if i + 1 < len(lines):
                            bottom_match = re.search(r"([0-9]{4,}\-[0-9]{4,}|[0-9\-]{6,15})", lines[i+1])
                            if bottom_match: doc_no = f"{doc_no} / {bottom_match.group(1)}"
                
                if "วันที่" in line or "Date" in line:
                    date_match = re.search(r"(\d{2}/\d{2}/\d{4})", line)
                    if date_match: doc_date = date_match.group(1)

            shopee_match = re.search(r"Included VAT\)?\s*([\d,]+\.\d{2})", text, re.IGNORECASE) or \
                           re.search(r"Total Value of Services \(Included VAT\)\s*([\d,]+\.\d{2})", text, re.IGNORECASE)
            spx_match = re.search(r"Total amount\s*([\d,]+\.\d{2})", text, re.IGNORECASE) or \
                        re.search(r"จำนวนเงินรวม/\s*Total\s*amount\s*([\d,]+\.\d{2})", text, re.IGNORECASE)
            
            if shopee and shopee_match: total_amount = shopee_match.group(1)
            elif spx and spx_match: total_amount = spx_match.group(1)
            
            try: total_amount = float(total_amount.replace(",", "")) if total_amount != "Unknown" else 0.0
            except: total_amount = 0.0
            
            data_list.append({"Page": idx+1, "Company": "Shopee" if shopee else "SPX Express", "Doc No.": doc_no, "Date": doc_date, "Total": total_amount})
    return pd.DataFrame(data_list)

# --- 2. ฟังก์ชันดึงข้อมูล Lazada ---
def get_lazada_expense_data(file):
    rows = []
    with pdfplumber.open(file) as pdf:
        for idx, page in enumerate(pdf.pages):
            text = page.extract_text() or ""
            for line in text.split("\n"):
                m = re.match(r"^(\d{2}/\d{2}/\d{4})\s+(.+)$", line.strip())
                if m:
                    date_str, rest = m.groups()
                    nums = re.findall(r"-?[\d,]+\.\d{2}", rest)
                    if nums:
                        d, mth, y = date_str.split("/")
                        rows.append({"Page": idx+1, "Date": f"{y}-{mth}-{d}", "Total": float(nums[0].replace(",", ""))})
    return pd.DataFrame(rows)

# --- 3. ส่วนหน้าเว็บ Streamlit ---
st.title("📊 โปรแกรมสรุปค่าใช้จ่าย")
tab1, tab2 = st.tabs(["Shopee", "Lazada"])

with tab1:
    f = st.file_uploader("อัปโหลดไฟล์ Shopee", type=["pdf"], key="shopee")
    if f:
        df = get_shopee_expense_data(f)
        st.dataframe(df)
        buf = io.BytesIO()
        df.to_excel(buf, index=False)
        st.download_button("ดาวน์โหลด Excel Shopee", buf.getvalue(), "Shopee_Expense.xlsx")

with tab2:
    f = st.file_uploader("อัปโหลดไฟล์ Lazada", type=["pdf"], key="lazada")
    if f:
        df = get_lazada_expense_data(f)
        st.dataframe(df)
        buf = io.BytesIO()
        df.to_excel(buf, index=False)
        st.download_button("ดาวน์โหลด Excel Lazada", buf.getvalue(), "Lazada_Expense.xlsx")
