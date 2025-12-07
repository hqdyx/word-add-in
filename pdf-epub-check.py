import streamlit as st
import requests
import os
import zipfile
import subprocess
import shutil
import time
import base64
from pathlib import Path

# --- 1. 页面配置：开启宽屏模式 ---
st.set_page_config(page_title="Doc2X 智能转换与校对工具", layout="wide")

# --- 2. 状态管理 (Session State) ---
# 用于在页面交互时保存数据，防止刷新丢失
if 'md_content' not in st.session_state:
    st.session_state.md_content = ""  # 存储 Markdown 内容
if 'pdf_bytes' not in st.session_state:
    st.session_state.pdf_bytes = None # 存储上传的 PDF 用于预览
if 'file_name' not in st.session_state:
    st.session_state.file_name = "document"

class Doc2XConverter:
    def __init__(self, api_key):
        self.api_key = api_key
        self.base_url = "https://v2.doc2x.com/api"

    def convert(self, file_obj, max_pages=None):
        """上传并转换 PDF"""
        try:
            files = {"file": (file_obj.name, file_obj, "application/pdf")}
            data = {"equation": "true"}  # 开启公式识别
            
            # 1. 上传文件
            upload_url = f"{self.base_url}/v2/parse/pdf"
            headers = {"Authorization": f"Bearer {self.api_key}"}
            
            with st.spinner("正在上传并解析文档 (Doc2X)..."):
                response = requests.post(upload_url, headers=headers, files=files, data=data)
                
            if response.status_code != 200:
                raise Exception(f"Upload failed: {response.text}")
                
            result = response.json()
            uuid = result['data']['uuid']
            
            # 2. 轮询状态
            status_url = f"{self.base_url}/v2/async/status?uuid={uuid}"
            while True:
                status_res = requests.get(status_url, headers=headers).json()
                status = status_res['data']['status']
                
                if status == 'success':
                    break
                elif status == 'failed':
                    raise Exception("Conversion failed on server side.")
                
                time.sleep(2)
            
            # 3. 下载 Markdown 结果
            result_url = f"{self.base_url}/v2/export?uuid={uuid}&type=markdown"
            md_res = requests.get(result_url, headers=headers)
            
            # 解压获取内容
            temp_zip = "temp_output.zip"
            with open(temp_zip, "wb") as f:
                f.write(md_res.content)
            
            extract_path = "temp_extracted"
            if os.path.exists(extract_path):
                shutil.rmtree(extract_path)
            
            with zipfile.ZipFile(temp_zip, 'r') as zip_ref:
                zip_ref.extractall(extract_path)
                
            # 读取主要的 Markdown 文件
            md_file = next(Path(extract_path).glob("*.md"))
            with open(md_file, "r", encoding="utf-8") as f:
                content = f.read()
                
            # 清理临时文件
            os.remove(temp_zip)
            # 注意：这里保留 temp_extracted 文件夹可能用于图片引用，
            # 但在简单文本编辑模式下，图片链接可能需要额外处理。
            # 为简化，这里暂不删除图片文件夹，让 Pandoc 能找到图片。
            
            return content

        except Exception as e:
            st.error(f"转换过程出错: {str(e)}")
            return None

class FormatConverter:
    @staticmethod
    def generate_epub(markdown_text, output_filename="output.epub"):
        """使用 Pandoc 将 Markdown 转换为 EPUB"""
        # 将编辑后的内容写入临时文件
        temp_md = "temp_edit.md"
        with open(temp_md, "w", encoding="utf-8") as f:
            f.write(markdown_text)
            
        try:
            # 检查 pandoc 是否存在
            try:
                subprocess.run(["pandoc", "-v"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            except FileNotFoundError:
                st.error("❌ 系统未安装 Pandoc，无法生成 EPUB。请在 packages.txt 中添加 pandoc。")
                return None

            # 运行转换命令
            cmd = [
                "pandoc",
                temp_md,
                "-o", output_filename,
                "--toc",  # 生成目录
                "--metadata", "title=Converted Document",
                "--split-level=2"
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True)
            
            if result.returncode != 0:
                st.error(f"Pandoc 转换失败:\n{result.stderr}")
                return None
                
            return output_filename
            
        except Exception as e:
            st.error(f"生成 EPUB 时发生错误: {str(e)}")
            return None

def display_pdf(file_bytes):
    """在 Streamlit 中嵌入 PDF 查看器"""
    base64_pdf = base64.b64encode(file_bytes).decode('utf-8')
    # 使用 HTML iframe 嵌入 PDF
    pdf_display = f'<iframe src="data:application/pdf;base64,{base64_pdf}" width="100%" height="800px" type="application/pdf"></iframe>'
    st.markdown(pdf_display, unsafe_allow_html=True)

# --- 主界面逻辑 ---

st.title("📚 夷卓汇：PDF 转 EPUB 智能校对工具")

# 侧边栏：设置与上传
with st.sidebar:
    st.header("1. 设置")
    # 优先从 Secrets 读取 Key，如果没有则显示输入框
    default_key = st.secrets.get("DOC2X_API_KEY", "")
    api_key = st.text_input("Doc2X API Key", value=default_key, type="password")
    
    st.header("2. 上传文件")
    uploaded_file = st.file_uploader("选择 PDF 文件", type=["pdf"])

    start_btn = st.button("🚀 开始转换 / 重置")

# --- 处理逻辑 ---

if start_btn and uploaded_file and api_key:
    # 保存文件名
    st.session_state.file_name = uploaded_file.name.rsplit('.', 1)[0]
    # 保存 PDF 二进制数据用于展示
    uploaded_file.seek(0)
    st.session_state.pdf_bytes = uploaded_file.read()
    uploaded_file.seek(0) # 重置指针用于上传
    
    converter = Doc2XConverter(api_key)
    result_text = converter.convert(uploaded_file)
    
    if result_text:
        st.session_state.md_content = result_text
        st.success("✅ 转换成功！请在右侧进行校对。")
        st.rerun() # 重新加载页面以显示编辑器

# --- 双栏校对界面 ---

if st.session_state.md_content:
    st.divider()
    st.subheader("📝 校对模式")
    
    col1, col2 = st.columns([1, 1]) # 左右等宽
    
    with col1:
        st.info("📄 原始文档 (PDF)")
        if st.session_state.pdf_bytes:
            display_pdf(st.session_state.pdf_bytes)
        else:
            st.warning("PDF 预览文件已过期，请重新上传。")

    with col2:
        st.info("✍️ 编辑 Markdown (可直接修改)")
        # 这里的 key="md_editor" 会自动绑定到 session_state
        # height=800 让高度和左边 PDF 差不多
        edited_content = st.text_area(
            "Markdown 内容", 
            value=st.session_state.md_content, 
            height=800,
            label_visibility="collapsed"
        )
        
        # 实时更新 Session State 中的内容
        if edited_content != st.session_state.md_content:
            st.session_state.md_content = edited_content

    # --- 底部导出栏 ---
    st.divider()
    st.header("3. 导出电子书")
    
    col_exp1, col_exp2 = st.columns([3, 1])
    with col_exp1:
        st.caption("提示：点击下载前，请确认上方的 Markdown 内容已修改完毕。系统将使用您修改后的内容生成电子书。")
    
    with col_exp2:
        if st.button("📖 生成并下载 EPUB"):
            epub_file = FormatConverter.generate_epub(
                st.session_state.md_content, # 使用当前编辑器里的内容
                f"{st.session_state.file_name}.epub"
            )
            
            if epub_file:
                with open(epub_file, "rb") as f:
                    st.download_button(
                        label="⬇️ 点击下载 EPUB",
                        data=f,
                        file_name=os.path.basename(epub_file),
                        mime="application/epub+zip"
                    )
else:
    if not uploaded_file:
        st.info("👋 请在左侧侧边栏上传 PDF 文件以开始。")
