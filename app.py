import streamlit as st
import pandas as pd
import pypdf
import re
import io

st.set_page_config(layout="wide", page_title="Shopee Report Processor")
st.title("📊 โปรแกรมสรุปรายได้ Shopee (เวอร์ชันแก้บัคข้อมูลผิด)")

def get_shopee_data(file):
    reader = pypdf.PdfReader(file)
    full_text = ""
    for page in reader.pages:
        full_text += page.extract_text() + "\n"
    
    # 1. รวมวันที่ที่โดนหั่นบรรทัด: แก้ 2026-05-0 \n 1 ให้เป็น 2026-05-01
    full_text = re.sub(r'(\d{4}-\d{2}-\d{1})\s*\n\s*(\d+)', r'\1\2', full_text)
    
    data = []
    lines = full_text.split('\n')
    
    for line in lines:
        # 2. ค้นหาวันที่ YYYY-MM-DD
        match = re.search(r'\d{4}-\d{2}-\d{2}', line)
        if match:
            date = match.group()
            # 3. ดึงตัวเลขทั้งหมดในบรรทัด (รองรับเครื่องหมายลบ)
            # เราใช้ Regex ดึงเลขที่มีทศนิยมหรือคอมม่า
            all_numbers = re.findall(r'(-?[\d,]+\.?\d*)', line)
            
            # 4. กรองตัวเลข:
            # - ต้องยาวพอ (มากกว่า 2 หลัก) เพื่อป้องกันเลขวันที่/เลขหน้า
            # - ต้องไม่รวมตัวเลขที่เป็นปีหรือส่วนของวันที่
            valid_numbers = []
            for n in all_numbers:
                clean_n = n.replace(',', '')
                # เงื่อนไข: เลขต้องไม่ใช่เลขปี (เช่น 2026) และยาว > 2
                if len(clean_n) > 2 and clean_n != "2026":
                    valid_numbers.append(float(clean_n))
            
            # 5. เก็บเฉพาะ 3 ค่าแรกที่เจอ (ราคาสินค้า, คืนเงิน, สนับสนุน)
            if len(valid_numbers) >= 3:
                data.append({
                    "วันที่": date,
                    "ราคาสินค้า": valid_numbers[0],
                    "ยอดคืนเงิน": valid_numbers[1],
                    "เงินสนับสนุน": valid_numbers[2]
                })
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
