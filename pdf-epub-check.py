import streamlit as st
import requests
import os
import zipfile
import subprocess
import shutil
import time
import base64
from pathlib import Path
import pypdf
from streamlit_pdf_viewer import pdf_viewer  # 必须在 requirements.txt 中添加 streamlit-pdf-viewer

# --- 1. 页面配置 ---
st.set_page_config(
    page_title="夷卓汇 - 智能文档转档平台", 
    page_icon="📚",
    layout="wide",
    initial_sidebar_state="expanded",
    menu_items={
        'About': "夷卓汇智能文档转换工具 v3.1 Professional"
    }
)

# --- 2. CSS 样式美化 ---
st.markdown("""
<style>
    .stApp { background-color: #f8f9fa; font-family: 'Segoe UI', sans-serif; }
    h1 { color: #2c3e50; font-weight: 800; letter-spacing: -0.5px; }
    .css-card { background-color: white; padding: 20px; border-radius: 12px; box-shadow: 0 4px 6px rgba(0,0,0,0.04); }
    .stButton>button { border-radius: 8px; font-weight: 600; transition: all 0.2s; }
    .stButton>button:hover { transform: translateY(-1px); box-shadow: 0 4px 12px rgba(0,0,0,0.1); }
    /* 导出区域样式 */
    .export-zone { background: #e3f2fd; padding: 20px; border-radius: 10px; border: 1px solid #bbdefb; }
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
if 'processing_done' not in st.session_state:
    st.session_state.processing_done = False

# --- 4. 核心功能类 ---

class CloudConverter:
    """处理云端转换逻辑"""
    def __init__(self, api_key):
        self.api_key = api_key
        self.base_url = "https://v2.doc2x.noedgeai.com"
        self.headers = {"Authorization": f"Bearer {api_key}"}

    def convert(self, file_obj, pdf_bytes):
        try:
            temp_dir = Path("./temp_uploads")
            temp_dir.mkdir(exist_ok=True)
            temp_file = temp_dir / file_obj.name
            
            with open(temp_file, "wb") as f:
                f.write(file_obj.getbuffer())
            
            st.session_state.pdf_bytes = pdf_bytes
            
            with st.status("🚀 AI 引擎正在处理...", expanded=True) as status:
                st.write("📡 建立安全连接...")
                uid, upload_url = self._preupload()
                
                st.write("☁️ 上传加密文档...")
                self._upload_file(temp_file, upload_url)
                
                st.write("🧠 AI 深度解析文档结构与公式...")
                self._wait_for_parsing(uid)
                
                st.write("📦 生成数据包...")
                self._trigger_export(uid)
                download_url = self._wait_for_export_result(uid)
                
                st.write("⬇️ 获取最终结果...")
                content = self._download_and_extract(download_url, temp_file)
                
                status.update(label="✅ 转换完成！", state="complete", expanded=False)
            
            if temp_file.exists(): temp_file.unlink()
            return content

        except Exception as e:
            st.error(f"❌ 转换中断: {str(e)}")
            return None

    def _preupload(self):
        res = requests.post(f"{self.base_url}/api/v2/parse/preupload", headers=self.headers)
        if res.status_code != 200: raise Exception("连接初始化失败")
        data = res.json()
        if data["code"] != "success": raise Exception("服务响应异常")
        return data["data"]["uid"], data["data"]["url"]

    def _upload_file(self, file_path, upload_url):
        with open(file_path, "rb") as f: requests.put(upload_url, data=f)

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
                progress_text.caption(f"当前进度: {prog}%")
                if status == "success":
                    bar.progress(1.0)
                    progress_text.empty()
                    break
                elif status == "failed": raise Exception("AI 解析失败")
            except Exception: continue

    def _trigger_export(self, uid):
        requests.post(f"{self.base_url}/api/v2/convert/parse", headers=self.headers, json={"uid": uid, "to": "md", "formula_mode": "normal", "filename": "output"})

    def _wait_for_export_result(self, uid):
        while True:
            time.sleep(1)
            res = requests.get(f"{self.base_url}/api/v2/convert/parse/result", headers=self.headers, params={"uid": uid})
            data = res.json()
            if data["code"] == "success" and data["data"]["status"] == "success": return data["data"]["url"]
            elif data["data"]["status"] == "failed": raise Exception("导出格式化失败")

    def _download_and_extract(self, url, original_file):
        r = requests.get(url)
        extract_path = Path(f"./output/{original_file.stem}")
        if extract_path.exists(): shutil.rmtree(extract_path)
        extract_path.mkdir(parents=True, exist_ok=True)
        zip_path = extract_path / "result.zip"
        with open(zip_path, 'wb') as f: f.write(r.content)
        with zipfile.ZipFile(zip_path, 'r') as z: z.extractall(extract_path)
        md_files = list(extract_path.glob("**/*.md"))
        if not md_files: raise Exception("结果包中未发现 Markdown 文件")
        with open(md_files[0], "r", encoding="utf-8") as f: return f.read()

class FormatConverter:
    @staticmethod
    def _prepare_temp_md(content):
        temp_md = "temp_edit.md"
        with open(temp_md, "w", encoding="utf-8") as f: f.write(content)
        return temp_md

    @staticmethod
    def generate_epub(markdown_text, output_filename="output.epub"):
        temp_md = FormatConverter._prepare_temp_md(markdown_text)
        try:
            cmd = ["pandoc", temp_md, "-o", output_filename, "--toc", "--split-level=2", "--metadata", "title=Ebook"]
            subprocess.run(cmd, check=True, capture_output=True)
            return output_filename
        except Exception as e:
            st.error(f"EPUB 生成失败: {e}")
            return None

    @staticmethod
    def generate_docx(markdown_text, output_filename="output.docx"):
        """生成 Word 文档"""
        temp_md = FormatConverter._prepare_temp_md(markdown_text)
        try:
            # check pandoc
            subprocess.run(["pandoc", "-v"], stdout=subprocess.PIPE, check=True)
            
            cmd = ["pandoc", temp_md, "-o", output_filename, "--reference-doc=reference.docx"]
            # 如果没有 reference.docx，pandoc 会使用默认样式，我们这里不强制要求 reference
            if not os.path.exists("reference.docx"):
                cmd = ["pandoc", temp_md, "-o", output_filename]
                
            subprocess.run(cmd, check=True, capture_output=True)
            return output_filename
        except subprocess.CalledProcessError as e:
            st.error(f"Pandoc 错误: {e.stderr.decode()}")
            return None
        except Exception as e:
            st.error(f"Word 生成失败: {e}")
            return None

def get_pdf_page_count(file_bytes):
    try:
        from io import BytesIO
        reader = pypdf.PdfReader(BytesIO(file_bytes))
        return len(reader.pages)
    except: return 0

def display_pdf(file_bytes):
    """
    使用 streamlit-pdf-viewer 修复 Cloud 上的显示问题
    """
    if file_bytes is None:
        st.info("💡 暂无 PDF 预览")
        return
    
    try:
        # width 设置为 None 会自适应容器宽度
        pdf_viewer(input=file_bytes, width=700, height=800)
    except Exception as e:
        st.error(f"PDF 组件加载失败: {str(e)}")

# --- 5. 主界面布局 ---

with st.sidebar:
    st.title("⚙️ 控制面板")
    with st.expander("🔑 密钥配置", expanded=True):
        try: default_key = st.secrets.get("DOC2X_API_KEY", "")
        except: default_key = ""
        api_key = st.text_input("API Key", value=default_key, type="password")

    st.markdown("---")
    mode = st.radio("选择模式", ["📄 PDF 转电子书", "📝 Markdown 转电子书"])
    st.markdown("---")
    
    if mode == "📄 PDF 转电子书":
        uploaded_file = st.file_uploader("上传文档", type=["pdf"])
        start_btn = st.button("开始转换 ✨", type="primary", use_container_width=True)
    else:
        uploaded_file = st.file_uploader("上传 Markdown", type=["md"])
        start_btn = st.button("加载文件 📂", type="primary", use_container_width=True)

st.title("📚 夷卓汇智能转档")
st.markdown("#### 让文档阅读更自由，支持多格式导出")

if start_btn and uploaded_file:
    st.session_state.file_name = uploaded_file.name.rsplit('.', 1)[0]
    st.session_state.processing_done = True
    
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
        content = uploaded_file.read().decode('utf-8')
        st.session_state.md_content = content
        st.session_state.pdf_bytes = None
        st.session_state.page_count = 0
        st.rerun()

# 结果展示与导出区
if st.session_state.md_content:
    # 状态栏
    col_m1, col_m2, col_m3 = st.columns(3)
    col_m1.metric("状态", "✅ 已就绪")
    col_m2.metric("页数", f"{st.session_state.page_count}")
    col_m3.metric("字符数", f"{len(st.session_state.md_content):,}")
    
    st.markdown("---")
    
    # 双栏编辑器
    col_preview, col_editor = st.columns([1, 1])
    with col_preview:
        st.subheader("📄 原始文档")
        display_pdf(st.session_state.pdf_bytes)
    with col_editor:
        st.subheader("✍️ 编辑 Markdown")
        with st.container():
            edited_content = st.text_area("Markdown源码", value=st.session_state.md_content, height=800, label_visibility="collapsed")
            if edited_content != st.session_state.md_content:
                st.session_state.md_content = edited_content

    # 底部导出操作 (新增多格式支持)
    st.markdown("---")
    st.subheader("📥 导出中心")
    
    st.markdown('<div class="export-zone">', unsafe_allow_html=True)
    exp_col1, exp_col2, exp_col3 = st.columns(3)
    
    # 1. 下载 Markdown
    with exp_col1:
        st.markdown("##### 📝 Markdown 源码")
        st.download_button(
            label="⬇️ 下载 .md 文件",
            data=st.session_state.md_content,
            file_name=f"{st.session_state.file_name}.md",
            mime="text/markdown",
            use_container_width=True
        )

    # 2. 下载 DOCX
    with exp_col2:
        st.markdown("##### 🟦 Word 文档")
        if st.button("⚙️ 生成并下载 Word", use_container_width=True):
            with st.spinner("正在转换 Word..."):
                docx_path = FormatConverter.generate_docx(
                    st.session_state.md_content,
                    f"{st.session_state.file_name}.docx"
                )
                if docx_path:
                    with open(docx_path, "rb") as f:
                        st.download_button(
                            label="⬇️ 点击下载 .docx",
                            data=f,
                            file_name=os.path.basename(docx_path),
                            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                            key="dl_docx_btn"
                        )
                    st.success("Word 生成成功")

    # 3. 下载 EPUB
    with exp_col3:
        st.markdown("##### 📖 电子书")
        if st.button("⚙️ 生成并下载 EPUB", use_container_width=True):
            with st.spinner("正在转换 EPUB..."):
                epub_path = FormatConverter.generate_epub(
                    st.session_state.md_content,
                    f"{st.session_state.file_name}.epub"
                )
                if epub_path:
                    with open(epub_path, "rb") as f:
                        st.download_button(
                            label="⬇️ 点击下载 .epub",
                            data=f,
                            file_name=os.path.basename(epub_path),
                            mime="application/epub+zip",
                            key="dl_epub_btn"
                        )
                    st.success("EPUB 生成成功")
    
    st.markdown('</div>', unsafe_allow_html=True)

elif not st.session_state.processing_done:
    st.markdown("""
    <div style="text-align: center; padding: 60px 0; color: #95a5a6;">
        <div style="font-size: 60px; margin-bottom: 20px;">📂</div>
        <h3>请在左侧上传文件开始工作</h3>
    </div>
    """, unsafe_allow_html=True)
