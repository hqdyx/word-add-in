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

# --- 2. CSS 样式优化 (解决头部过大问题) ---
st.markdown("""
<style>
    /* 1. 极度压缩页面顶部空白 */
    .block-container {
        padding-top: 1rem !important;
        padding-bottom: 1rem !important;
    }
    header {visibility: hidden;} /* 隐藏 Streamlit 默认的汉堡菜单栏背景 */
    
    /* 2. 全局字体与背景 */
    .stApp { background-color: #f8f9fa; font-family: 'Segoe UI', sans-serif; }
    
    /* 3. 自定义紧凑标题 */
    .compact-title {
        color: #2c3e50;
        font-size: 1.8rem;
        font-weight: 800;
        margin-bottom: 0px;
        padding-bottom: 10px;
        border-bottom: 2px solid #e9ecef;
    }
    
    /* 4. 导出区域样式 */
    .export-zone { 
        background: white; 
        padding: 15px; 
        border-radius: 10px; 
        border: 1px solid #e0e0e0;
        margin-top: 20px;
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
    st.session_state.work_dir = None # 存储解压后的工作目录路径

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
                
                # 保存工作目录到 session，这对后续生成 EPUB 至关重要（为了找图片）
                st.session_state.work_dir = str(extract_path)
                
                status.update(label="✅ 转换完成！", state="complete", expanded=False)
            
            if temp_file.exists(): temp_file.unlink()
            return content

        except Exception as e:
            st.error(f"❌ 转换中断: {str(e)}")
            return None

    # ... (原有网络请求方法保持不变) ...
    def _preupload(self):
        res = requests.post(f"{self.base_url}/api/v2/parse/preupload", headers=self.headers)
        if res.status_code != 200: raise Exception("初始化失败")
        data = res.json()
        if data["code"] != "success": raise Exception("API 响应错误")
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
                progress_text.caption(f"解析进度: {prog}%")
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
            elif data["data"]["status"] == "failed": raise Exception("导出失败")

    def _download_and_extract(self, url, original_file):
        r = requests.get(url)
        # 使用绝对路径，确保 Pandoc 能找到
        base_output_dir = Path("./output").resolve()
        extract_path = base_output_dir / original_file.stem
        
        if extract_path.exists(): shutil.rmtree(extract_path)
        extract_path.mkdir(parents=True, exist_ok=True)
        
        zip_path = extract_path / "result.zip"
        with open(zip_path, 'wb') as f: f.write(r.content)
        
        with zipfile.ZipFile(zip_path, 'r') as z: z.extractall(extract_path)
        
        md_files = list(extract_path.glob("**/*.md"))
        if not md_files: raise Exception("未找到 MD 文件")
        
        with open(md_files[0], "r", encoding="utf-8") as f: content = f.read()
        
        return content, extract_path

class FormatConverter:
    @staticmethod
    def generate_epub(markdown_text, work_dir, output_filename="output.epub"):
        """
        生成 EPUB
        关键修复：将 cwd 设置为 work_dir，确保 Pandoc 能找到图片
        """
        if not work_dir or not os.path.exists(work_dir):
            st.error("工作目录丢失，无法生成含图片的文档")
            return None

        # 在工作目录下创建临时 md 文件
        temp_md_path = os.path.join(work_dir, "temp_render.md")
        output_path = os.path.join(work_dir, output_filename)
        
        with open(temp_md_path, "w", encoding="utf-8") as f:
            f.write(markdown_text)
            
        try:
            # 检查 pandoc
            subprocess.run(["pandoc", "-v"], stdout=subprocess.PIPE, check=True)
            
            cmd = [
                "pandoc", 
                "temp_render.md",  # 只写文件名，因为我们会在 cwd 下运行
                "-o", output_filename,
                "--toc", 
                "--split-level=2", 
                "--metadata", "title=Converted Document"
            ]
            
            # 关键：cwd=work_dir
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
        if not work_dir or not os.path.exists(work_dir): return None
        
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
    """
    将 Markdown 中的本地图片路径替换为 Base64 编码，
    以便在 Streamlit 预览中显示。
    """
    if not work_dir:
        return md_content

    def replace_image(match):
        alt_text = match.group(1)
        image_path = match.group(2)
        
        # 尝试在工作目录中找到图片
        full_path = Path(work_dir) / image_path
        
        if full_path.exists():
            try:
                with open(full_path, "rb") as img_file:
                    b64_string = base64.b64encode(img_file.read()).decode()
                    # 根据后缀名判断 mime type
                    mime_type = "image/png"
                    if image_path.lower().endswith('.jpg') or image_path.lower().endswith('.jpeg'):
                        mime_type = "image/jpeg"
                    
                    return f"![{alt_text}](data:{mime_type};base64,{b64_string})"
            except:
                pass
        return match.group(0) # 找不到就原样返回

    # 正则匹配 ![](path)
    pattern = r'!\[(.*?)\]\((.*?)\)'
    return re.sub(pattern, replace_image, md_content)

def get_pdf_page_count(file_bytes):
    try:
        from io import BytesIO
        reader = pypdf.PdfReader(BytesIO(file_bytes))
        return len(reader.pages)
    except: return 0

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

with st.sidebar:
    st.header("⚙️ 控制面板")
    with st.expander("🔑 密钥配置", expanded=True):
        try: default_key = st.secrets.get("DOC2X_API_KEY", "")
        except: default_key = ""
        api_key = st.text_input("API Key", value=default_key, type="password")

    mode = st.radio("选择模式", ["📄 PDF 转电子书", "📝 Markdown 转电子书"])
    
    if mode == "📄 PDF 转电子书":
        uploaded_file = st.file_uploader("上传文档", type=["pdf"])
        start_btn = st.button("开始转换 ✨", type="primary", use_container_width=True)
    else:
        uploaded_file = st.file_uploader("上传 Markdown", type=["md"])
        start_btn = st.button("加载文件 📂", type="primary", use_container_width=True)

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
        # Markdown 模式：创建一个临时工作目录
        temp_work = Path("./output/temp_md_upload").resolve()
        if temp_work.exists(): shutil.rmtree(temp_work)
        temp_work.mkdir(parents=True, exist_ok=True)
        
        content = uploaded_file.read().decode('utf-8')
        st.session_state.md_content = content
        st.session_state.pdf_bytes = None
        st.session_state.page_count = 0
        st.session_state.work_dir = str(temp_work) # 设置工作目录
        st.rerun()

# 结果展示区
if st.session_state.md_content:
    # 状态栏
    col_stat1, col_stat2, col_stat3 = st.columns([1,1,2])
    with col_stat1: st.caption(f"📄 页数: {st.session_state.page_count}")
    with col_stat2: st.caption(f"📝 字符: {len(st.session_state.md_content):,}")
    
    # 布局：左侧 PDF，右侧 Tabs (预览/编辑)
    col_left, col_right = st.columns([1, 1])
    
    with col_left:
        st.markdown("##### 📄 原始文档")
        display_pdf(st.session_state.pdf_bytes)
    
    with col_right:
        # 使用 Tabs 切换预览和编辑
        tab_preview, tab_edit = st.tabs(["👁️ 渲染预览 (含图片)", "📝 源码编辑"])
        
        with tab_preview:
            # 实时将图片转为 Base64 以供预览
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

    # 底部导出中心
    st.markdown('<div class="export-zone">', unsafe_allow_html=True)
    st.markdown("#### 📥 导出中心")
    
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
        if st.button("🟦 生成 Word (.docx)", use_container_width=True):
            with st.spinner("生成中..."):
                docx_path = FormatConverter.generate_docx(
                    st.session_state.md_content,
                    st.session_state.work_dir, # 传入工作目录
                    f"{st.session_state.file_name}.docx"
                )
                if docx_path and os.path.exists(docx_path):
                    with open(docx_path, "rb") as f:
                        st.download_button(
                            label="⬇️ 点击下载 Word",
                            data=f,
                            file_name=os.path.basename(docx_path),
                            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                            key="dl_docx_final"
                        )
                    st.success("Word 生成成功")

    with exp_c3:
        if st.button("📖 生成电子书 (.epub)", use_container_width=True):
            with st.spinner("生成中..."):
                epub_path = FormatConverter.generate_epub(
                    st.session_state.md_content,
                    st.session_state.work_dir, # 传入工作目录
                    f"{st.session_state.file_name}.epub"
                )
                if epub_path and os.path.exists(epub_path):
                    with open(epub_path, "rb") as f:
                        st.download_button(
                            label="⬇️ 点击下载 EPUB",
                            data=f,
                            file_name=os.path.basename(epub_path),
                            mime="application/epub+zip",
                            key="dl_epub_final"
                        )
                    st.success("EPUB 生成成功")
    
    st.markdown('</div>', unsafe_allow_html=True)

else: 
    st.markdown("""
    <div style="text-align: center; padding: 60px 0; color: #95a5a6;">
        <div style="font-size: 60px; margin-bottom: 20px;">📂</div>
        <h3>请在左侧上传文件开始工作</h3>
    </div>
    """, unsafe_allow_html=True)


