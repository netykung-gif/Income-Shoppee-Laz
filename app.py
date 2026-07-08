import streamlit as st
import pandas as pd
import pypdf
import re
import io

st.set_page_config(layout="wide", page_title="Shopee Report Processor")
st.title("📊 โปรแกรมสรุปรายได้ Shopee (เวอร์ชันแก้บัคข้อมูลผิด)")

def get_shopee_data(file):
    reader = pypdf.PdfReader(file)
    data = []
    
    # ดึงข้อความมาทั้งหมดแล้วทำความสะอาดก่อน
    full_text = ""
    for page in reader.pages:
        full_text += page.extract_text() + "\n"
    
    # Regex แบบใหม่: หาบรรทัดที่เริ่มด้วยวันที่ YYYY-MM-DD
    # แล้วดึงตัวเลข 3 ชุดถัดไป โดยใช้ช่องว่างเป็นตัวคั่น
    lines = full_text.split('\n')
    for line in lines:
        # เช็คว่าขึ้นต้นด้วยวันที่หรือไม่ (เช่น 2026-06-01)
        if re.match(r'^\d{4}-\d{2}-\d{2}', line):
            # ลบอักขระพิเศษและแยกด้วยช่องว่าง
            parts = re.split(r'\s+', line.strip())
            
            # กรองเอาเฉพาะข้อมูลที่มีตัวเลข (ป้องกันบรรทัดขยะ)
            # เราต้องการ [วันที่, ราคาสินค้า, ยอดคืนเงิน, เงินสนับสนุน]
            # หมายเหตุ: Shopee เดือน 5-6 วันที่อยู่ index 0 
            # เลขตัวแรกมักจะอยู่ที่ index 1 หรือ 2 แล้วแต่ความเพี้ยนของ PDF
            
            # ดึงเลขทั้งหมดในบรรทัดนี้ออกมา (เอาเฉพาะเลข)
            nums = re.findall(r'(-?[\d,]+\.?\d*)', line)
            
            # ถ้ามีเลขอย่างน้อย 3 ชุดขึ้นไป
            if len(nums) >= 3:
                try:
                    data.append({
                        "วันที่": line[:10],
                        "ราคาสินค้า": float(nums[0].replace(',', '')),
                        "ยอดคืนเงิน": float(nums[1].replace(',', '')),
                        "เงินสนับสนุน": float(nums[2].replace(',', ''))
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
