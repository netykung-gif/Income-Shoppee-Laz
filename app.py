import streamlit as st
import pandas as pd
import pypdf
import re
import io

st.set_page_config(layout="wide", page_title="Shopee Report Processor")
st.title("📊 โปรแกรมสรุปรายได้ Shopee (ฉบับรองรับทุกเดือน)")

def get_shopee_data(file):
    reader = pypdf.PdfReader(file)
    data = []
    
    # รวมข้อความทุกหน้า
    full_text = ""
    for page in reader.pages:
        full_text += page.extract_text() + "\n"
    
    # แยกบรรทัดและหาเฉพาะบรรทัดที่มีวันที่ (YYYY-MM-DD)
    lines = full_text.split('\n')
    for line in lines:
        # ค้นหา pattern วันที่
        if re.search(r'\d{4}-\d{2}-\d{2}', line):
            date = re.search(r'\d{4}-\d{2}-\d{2}', line).group()
            # ดึงตัวเลขทั้งหมดในบรรทัดนั้น (รองรับเครื่องหมายลบและคอมม่า)
            numbers = re.findall(r'(-?[\d,]+\.?\d*)', line)
            
            # เราสนใจแค่ 3 ค่าแรกที่สำคัญเสมอ: ราคาสินค้า, ยอดคืนเงิน, เงินสนับสนุน
            if len(numbers) >= 3:
                try:
                    data.append({
                        "วันที่": date,
                        "ราคาสินค้า": float(numbers[0].replace(',', '')),
                        "ยอดคืนเงิน": float(numbers[1].replace(',', '')),
                        "เงินสนับสนุน": float(numbers[2].replace(',', ''))
                    })
                except: continue
                
    return pd.DataFrame(data)

# --- UI ส่วนแสดงผล ---
uploaded_file = st.file_uploader("อัปโหลดไฟล์ PDF รายงาน Shopee", type=["pdf"])

if uploaded_file is not None:
    df = get_shopee_data(uploaded_file)
    
    if not df.empty:
        # บังคับตั้งชื่อคอลัมน์ให้แน่นอนก่อนคำนวณ
        df.columns = ["วันที่", "ราคาสินค้า", "ยอดคืนเงิน", "เงินสนับสนุน"]
        
        # คำนวณสูตร
        df["ยอดสุทธิ"] = (df["ราคาสินค้า"] - df["ยอดคืนเงิน"].abs()) + df["เงินสนับสนุน"]
        
        st.success(f"พบข้อมูลทั้งหมด {len(df)} รายการ")
        st.dataframe(df, use_container_width=True)
        
        # ปุ่มดาวน์โหลด
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            df.to_excel(writer, index=False)
        
        st.download_button("📥 ดาวน์โหลด Excel", output.getvalue(), "Shopee_Report_Final.xlsx", "application/vnd.ms-excel")
    else:
        st.error("ไม่พบข้อมูลที่ตรงเงื่อนไข กรุณาตรวจสอบไฟล์ PDF")
