import streamlit as st
import pandas as pd
import pypdf
import re
import io

st.set_page_config(layout="wide", page_title="Shopee Report Processor")
st.title("📊 โปรแกรมสรุปรายได้ Shopee (เวอร์ชันแก้บัคข้อมูลผิด)")

def get_shopee_data(file):
    reader = pypdf.PdfReader(file)
    text = ""
    for page in reader.pages:
        text += page.extract_text() + "\n"
    
    # regex นี้จะจับวันที่ YYYY-MM-DD ก่อน แล้วค่อยตามหาตัวเลขจำนวนเงิน
    # โดยใช้ [\s\S]*? เพื่อข้ามการขึ้นบรรทัดใหม่ที่แทรกอยู่ระหว่างตัวเลข
    pattern = r'(\d{4}-\d{2}-\d{2})[\s\S]*?([\d,]+\.?\d*)[\s\S]*?(-?[\d,]+\.?\d*)[\s\S]*?(-?[\d,]+\.?\d*)'
    
    matches = re.findall(pattern, text)
    data = []
    
    for m in matches:
        # ข้ามรายการที่อาจจะเป็นตัวเลขปีหรือข้อมูลสรุปที่ไม่ใช่รายการรายวัน
        if m[0] == "2026": continue 
        
        try:
            data.append({
                "วันที่": m[0],
                "ราคาสินค้า": float(m[1].replace(',', '')),
                "ยอดคืนเงิน": float(m[2].replace(',', '')),
                "เงินสนับสนุน": float(m[3].replace(',', ''))
            })
        except: continue
        
    return pd.DataFrame(data)

# --- ส่วน UI ---
uploaded_file = st.file_uploader("อัปโหลดไฟล์ PDF รายงาน Shopee", type=["pdf"])

if uploaded_file is not None:
    df = get_shopee_data(uploaded_file)
    
    if not df.empty:
        # คำนวณสูตร
        df["ยอดสุทธิ"] = (df["ราคาสินค้า"] - df["ยอดคืนเงิน"].abs()) + df["เงินสนับสนุน"]
        
        st.success(f"พบข้อมูลทั้งหมด {len(df)} รายการ")
        st.dataframe(df, use_container_width=True)
        
        # ปุ่มดาวน์โหลด
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            df.to_excel(writer, index=False)
        st.download_button("📥 ดาวน์โหลด Excel", output.getvalue(), "Shopee_Report_Refactored.xlsx", "application/vnd.ms-excel")
    else:
        st.error("ไม่พบข้อมูลที่ถูกต้องในไฟล์นี้")
