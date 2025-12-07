import streamlit as st
import requests
import os
import zipfile
import subprocess
import shutil
import time
import base64
import re
from pathlib import Path
import pypdf
from streamlit_pdf_viewer import pdf_viewer

# --- 1. 页面配置 ---
st.set_page_config(
    page_title="夷卓汇 - 智能文档转档平台", 
    page_icon="📚",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- 2. CSS 样式优化 (修复侧边栏显示问题) ---
st.markdown("""
<style>
    /* 1. 压缩页面顶部空白，但保留 header 可见性 */
    .block-container {
        padding-top: 1rem !important;
        padding-bottom: 1rem !important;
    }
    
    /* 确保侧边栏可见 */
    section[data-testid="stSidebar"] {
        background: linear-gradient(180deg, #667eea 0%, #764ba2 100%);
        min-width: 280px !important;
    }
    
    section[data-testid="stSidebar"] > div:first-child {
        background: rgba(255, 255, 255, 0.98);
        border-radius: 15px;
        margin: 15px;
        padding: 20px;
    }
    
    /* 2. 全局字体与背景 */
    .stApp { 
        background-color: #f8f9fa; 
        font-family: 'Segoe UI', sans-serif; 
    }
    
    /* 3. 自定义紧凑标题 */
    .compact-title {
        color: #2c3e50;
        font-size: 1.8rem;
        font-weight: 800;
        margin-bottom: 5px;
        padding-bottom: 10px;
        border-bottom: 2px solid #e9ecef;
    }
    
    /* 4. 导出区域样式 */
    .export-zone { 
        background: white; 
        padding: 20px; 
        border-radius: 10px; 
        border: 1px solid #e0e0e0;
        margin-top: 20px;
        box-shadow: 0 2px 8px rgba(0,0,0,0.05);
    }
    
    /* 5. 调整 Tabs 样式 */
    .stTabs [data-baseweb="tab-list"] {
        gap: 10px;
    }
    .stTabs [data-baseweb="tab"] {
        height: 40px;
        background-color: white;
        border-radius: 5px;
        padding: 0 20px;
        border: 1px solid #ddd;
    }
    .stTabs [aria-selected="true"] {
        background-color: #e3f2fd;
        border-color: #2196f3;
        font-weight: bold;
    }
    
    /* 6. 侧边栏内部样式优化 */
    section[data-testid="stSidebar"] .stButton>button {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        color: white;
        font-weight: 600;
        border: none;
        transition: all 0.3s;
    }
    
    section[data-testid="stSidebar"] .stButton>button:hover {
        transform: translateY(-2px);
        box-shadow: 0 4px 12px rgba(102, 126, 234, 0.4);
    }
    
    /* 7. 文件上传器样式 */
    .uploadedFile {
        background: #f8f9fa;
        border-radius: 8px;
        padding: 10px;
        margin: 10px 0;
    }
    
    /* 8. 优化信息框 */
    .stInfo {
        background-color: #e3f2fd;
        border-left: 4px solid #2196f3;
        padding: 12px;
        border-radius: 5px;
    }

    /* 9. 调整 PDF 显示框的高度 */
    .pdf-container {
        height: 600px !important;
    }

    /* 10. 调整 Markdown 编辑框高度 */
    .markdown-container {
        height: 650px !important;
    }
</style>
""", unsafe_allow_html=True)

# --- 3. 状态管理 ---
if 'md_content' not in st.session_state:
    st.session_state.md_content = ""
if 'pdf_bytes' not in st.session_state:
    st.session_state.pdf_bytes = None
if 'file_name' not in st.session_state:
    st.session_state.file_name = "document"
if 'page_count' not in st.session_state:
    st.session_state.page_count = 0
if 'work_dir' not in st.session_state:
    st.session_state.work_dir = None

# --- 4. 核心功能类 ---
class CloudConverter:
    """处理云端转换逻辑"""
    def __init__(self, api_key):
        self.api_key = api_key
        self.base_url = "https://v2.doc2x.noedgeai.com"
        self.headers = {"Authorization": f"Bearer {api_key}"}

    def convert(self, file_obj, pdf_bytes):
        try:
            # 1. 准备上传
            temp_dir = Path("./temp_uploads")
            temp_dir.mkdir(exist_ok=True)
            temp_file = temp_dir / file_obj.name
            
            with open(temp_file, "wb") as f:
                f.write(file_obj.getbuffer())
            
            st.session_state.pdf_bytes = pdf_bytes
            
            # 2. 转换流程
            with st.status("🚀 AI 引擎正在处理...", expanded=True) as status:
                st.write("📡 连接云端引擎...")
                uid, upload_url = self._preupload()
                
                st.write("☁️ 上传文档...")
                self._upload_file(temp_file, upload_url)
                
                st.write("🧠 AI 解析排版与公式...")
                self._wait_for_parsing(uid)
                
                st.write("📦 打包资源...")
                self._trigger_export(uid)
                download_url = self._wait_for_export_result(uid)
                
                st.write("⬇️ 下载并解压...")
                content, extract_path = self._download_and_extract(download_url, temp_file)
                
                st.session_state.work_dir = str(extract_path)
                
                status.update(label="✅ 转换完成！", state="complete", expanded=False)
            
            if temp_file.exists(): temp_file.unlink()
            return content

        except Exception as e:
            st.error(f"❌ 转换中断: {str(e)}")
            return None

    def _preupload(self):
        res = requests.post(f"{self.base_url}/api/v2/parse/preupload", headers=self.headers)
        if res.status_code != 200: raise Exception("初始化失败")
        data = res.json()
        if data["code"] != "success": raise Exception("API 响应错误")
        return data["data"]["uid"], data["data"]["url"]

    def _upload_file(self, file_path, upload_url):
        with open(file_path, "rb") as f: 
            requests.put(upload_url, data=f)

    def _wait_for_parsing(self, uid):
        progress_text = st.empty()
        bar = st.progress(0)
        while True:
            time.sleep(1.5)
            try:
                res = requests.get(f"{self.base_url}/api/v2/parse/status", headers=self.headers, params={"uid": uid})
                data = res.json()
                if data["code"] != "success": continue
                status = data["data"]["status"]
                prog = data["data"].get("progress", 0)
                bar.progress(min(prog / 100, 0.95))
                progress_text.caption(f"解析进度: {prog}%")
                if status == "success":
                    bar.progress(1.0)
                    progress_text.empty()
                    break
                elif status == "failed": raise Exception("AI 解析失败")
            except Exception: continue

    def _trigger_export(self, uid):
        requests.post(f"{self.base_url}/api/v2/convert/parse", headers=self.headers, 
                     json={"uid": uid, "to": "md", "formula_mode": "normal", "filename": "output"})

    def _wait_for_export_result(self, uid):
        while True:
            time.sleep(1)
            res = requests.get(f"{self.base_url}/api/v2/convert/parse/result", headers=self.headers, params={"uid": uid})
            data = res.json()
            if data["code"] == "success" and data["data"]["status"] == "success": 
                return data["data"]["url"]
            elif data["data"]["status"] == "failed": 
                raise Exception("导出失败")

    def _download_and_extract(self, url, original_file):
        r = requests.get(url)
        base_output_dir = Path("./output").resolve()
        extract_path = base_output_dir / original_file.stem
        
        if extract_path.exists(): shutil.rmtree(extract_path)
        extract_path.mkdir(parents=True, exist_ok=True)
        
        zip_path = extract_path / "result.zip"
        with open(zip_path, 'wb') as f: f.write(r.content)
        
        with zipfile.ZipFile(zip_path, 'r') as z: z.extractall(extract_path)
        
        md_files = list(extract_path.glob("**/*.md"))
        if not md_files: raise Exception("未找到 MD 文件")
        
        with open(md_files[0], "r", encoding="utf-8") as f: 
            content = f.read()
        
        return content, extract_path

class FormatConverter:
    @staticmethod
    def generate_epub(markdown_text, work_dir, output_filename="output.epub"):
        if not work_dir or not os.path.exists(work_dir):
            st.error("工作目录丢失，无法生成含图片的文档")
            return None

        temp_md_path = os.path.join(work_dir, "temp_render.md")
        output_path = os.path.join(work_dir, output_filename)
        
        with open(temp_md_path, "w", encoding="utf-8") as f:
            f.write(markdown_text)
            
        try:
            subprocess.run(["pandoc", "-v"], stdout=subprocess.PIPE, check=True)
            
            cmd = [
                "pandoc", 
                "temp_render.md",
                "-o", output_filename,
                "--toc", 
                "--metadata", "title=Converted Document"
            ]
            
            subprocess.run(cmd, cwd=work_dir, check=True, capture_output=True)
            return output_path
            
        except subprocess.CalledProcessError as e:
            st.error(f"Pandoc 错误 (Exit {e.returncode}):\n{e.stderr.decode()}")
            return None
        except Exception as e:
            st.error(f"生成失败: {e}")
            return None

    @staticmethod
    def generate_docx(markdown_text, work_dir, output_filename="output.docx"):
        if not work_dir or not os.path.exists(work_dir): 
            return None
        
        temp_md_path = os.path.join(work_dir, "temp_render.md")
        output_path = os.path.join(work_dir, output_filename)
        
        with open(temp_md_path, "w", encoding="utf-8") as f:
            f.write(markdown_text)
            
        try:
            cmd = ["pandoc", "temp_render.md", "-o", output_filename]
            subprocess.run(cmd, cwd=work_dir, check=True, capture_output=True)
            return output_path
        except Exception as e:
            st.error(f"Word 生成失败: {e}")
            return None

def process_images_for_preview(md_content, work_dir):
    if not work_dir:
        return md_content

    def replace_image(match):
        alt_text = match.group(1)
        image_path = match.group(2)
        full_path = Path(work_dir) / image_path
        
        if full_path.exists():
            try:
                with open(full_path, "rb") as img_file:
                    b64_string = base64.b64encode(img_file.read()).decode()
                    mime_type = "image/png"
                    if image_path.lower().endswith(('.jpg', '.jpeg')):
                        mime_type = "image/jpeg"
                    return f"![{alt_text}](data:{mime_type};base64,{b64_string})"
            except:
                pass
        return match.group(0)

    pattern = r'!\[(.*?)\]\((.*?)\)'
    return re.sub(pattern, replace_image, md_content)

def get_pdf_page_count(file_bytes):
    try:
        from io import BytesIO
        reader = pypdf.PdfReader(BytesIO(file_bytes))
        return len(reader.pages)
    except: 
        return 0

def display_pdf(file_bytes):
    if file_bytes is None:
        st.info("💡 暂无 PDF 预览")
        return
    try:
        pdf_viewer(input=file_bytes, width=700, height=800)
    except Exception as e:
        st.error(f"PDF 组件加载失败: {str(e)}")

# --- 5. 主界面布局 ---

# 页面顶部标题
st.markdown('<div class="compact-title">📚 夷卓汇智能转档</div>', unsafe_allow_html=True)

# === 侧边栏 ===
with st.sidebar:
    st.markdown("### ⚙️ 控制面板")
    
    with st.expander("🔑 密钥配置", expanded=True):
        try: 
            default_key = st.secrets.get("DOC2X_API_KEY", "")
        except: 
            default_key = ""
        api_key = st.text_input("API Key", value=default_key, type="password", help="输入您的 API 密钥")

    st.markdown("---")
    
    st.markdown("### 📂 选择模式")
    mode = st.radio(
        "转换模式",
        ["📄 PDF 转电子书", "📝 Markdown 转电子书"],
        label_visibility="collapsed"
    )
    
    st.markdown("---")
    st.markdown("### 📤 上传文件")
    
    if mode == "📄 PDF 转电子书":
        uploaded_file = st.file_uploader("选择 PDF", type=["pdf"], help="支持最大 50MB")
        start_btn = st.button("🚀 开始转换", type="primary", use_container_width=True)
    else:
        uploaded_file = st.file_uploader("选择 Markdown", type=["md", "markdown"])
        start_btn = st.button("📂 加载文件", type="primary", use_container_width=True)
    
    # 使用说明
    st.markdown("---")
    with st.expander("ℹ️ 使用说明"):
        st.markdown("""
        **PDF 转电子书：**
        1. 输入 API Key
        2. 上传 PDF 文件
        3. AI 智能解析
        4. 预览编辑内容
        5. 导出电子书
        
        **Markdown 转电子书：**
        1. 上传 Markdown
        2. 预览编辑
        3. 导出电子书
        """)

# === 文件处理逻辑 ===
if start_btn and uploaded_file:
    st.session_state.file_name = uploaded_file.name.rsplit('.', 1)[0]
    
    if mode == "📄 PDF 转电子书":
        if not api_key:
            st.error("🚫 请先在左侧输入 API Key")
        else:
            uploaded_file.seek(0)
            pdf_bytes = uploaded_file.read()
            uploaded_file.seek(0)
            st.session_state.page_count = get_pdf_page_count(pdf_bytes)
            
            converter = CloudConverter(api_key)
            result_text = converter.convert(uploaded_file, pdf_bytes)
            
            if result_text:
                st.session_state.md_content = result_text
                st.rerun()
    else:
        temp_work = Path("./output/temp_md_upload").resolve()
        if temp_work.exists(): 
            shutil.rmtree(temp_work)
        temp_work.mkdir(parents=True, exist_ok=True)
        
        content = uploaded_file.read().decode('utf-8')
        st.session_state.md_content = content
        st.session_state.pdf_bytes = None
        st.session_state.page_count = 0
        st.session_state.work_dir = str(temp_work)
        st.rerun()

# === 结果展示区 ===
if st.session_state.md_content:
    # 状态栏
    col_stat1, col_stat2 = st.columns([1, 3])
    with col_stat1: 
        st.metric("📄 页数", st.session_state.page_count)
    with col_stat2: 
        st.metric("📝 字符数", f"{len(st.session_state.md_content):,}")
    
    st.markdown("---")
    
    # 双栏布局
    col_left, col_right = st.columns([1, 1])
    
    with col_left:
        st.markdown("#### 📄 原始文档")
        display_pdf(st.session_state.pdf_bytes)
    
    with col_right:
        st.markdown("#### ✍️ 内容编辑")
        tab_preview, tab_edit = st.tabs(["👁️ 渲染预览", "📝 源码编辑"])
        
        with tab_preview:
            preview_content = process_images_for_preview(
                st.session_state.md_content, 
                st.session_state.work_dir
            )
            st.markdown(preview_content, unsafe_allow_html=True)
            
        with tab_edit:
            edited_content = st.text_area(
                "Markdown 源码", 
                value=st.session_state.md_content, 
                height=750, 
                label_visibility="collapsed"
            )
            if edited_content != st.session_state.md_content:
                st.session_state.md_content = edited_content

    # 导出中心
    st.markdown('<div class="export-zone">', unsafe_allow_html=True)
    st.markdown("### 📥 导出中心")
    
    exp_c1, exp_c2, exp_c3 = st.columns(3)
    
    with exp_c1:
        st.download_button(
            label="📝 下载 Markdown",
            data=st.session_state.md_content,
            file_name=f"{st.session_state.file_name}.md",
            mime="text/markdown",
            use_container_width=True
        )

    with exp_c2:
        if st.button("🟦 生成 Word", use_container_width=True):
            with st.spinner("生成中..."):
                docx_path = FormatConverter.generate_docx(
                    st.session_state.md_content,
                    st.session_state.work_dir,
                    f"{st.session_state.file_name}.docx"
                )
                if docx_path and os.path.exists(docx_path):
                    with open(docx_path, "rb") as f:
                        st.download_button(
                            label="⬇️ 下载 Word",
                            data=f,
                            file_name=os.path.basename(docx_path),
                            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                            key="dl_docx"
                        )

    with exp_c3:
        if st.button("📖 生成 EPUB", use_container_width=True):
            with st.spinner("生成中..."):
                epub_path = FormatConverter.generate_epub(
                    st.session_state.md_content,
                    st.session_state.work_dir,
                    f"{st.session_state.file_name}.epub"
                )
                if epub_path and os.path.exists(epub_path):
                    with open(epub_path, "rb") as f:
                        st.download_button(
                            label="⬇️ 下载 EPUB",
                            data=f,
                            file_name=os.path.basename(epub_path),
                            mime="application/epub+zip",
                            key="dl_epub"
                        )
    
    st.markdown('</div>', unsafe_allow_html=True)

else:
    # 欢迎页面
    st.markdown("""
    <div style="text-align: center; padding: 80px 20px; color: #95a5a6;">
        <div style="font-size: 80px; margin-bottom: 30px;">📂</div>
        <h2 style="color: #2c3e50;">欢迎使用夷卓汇智能转档平台</h2>
        <p style="font-size: 18px; margin-top: 20px;">
            👈 请在左侧侧边栏选择模式并上传文件开始工作
        </p>
    </div>
    """, unsafe_allow_html=True)
