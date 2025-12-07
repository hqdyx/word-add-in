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

# --- 2. CSS 样式优化 ---
st.markdown("""
# --- 2. CSS 样式优化 ---
st.markdown("""
<style>
    /* 1. 隐藏顶部工具栏（Deploy、Share 等） */
    header[data-testid="stHeader"] {
        display: none !important;
    }
    
    /* 2. 隐藏汉堡菜单（三条线图标） */
    button[kind="header"] {
        display: none !important;
    }
    
    /* 3. 压缩页面顶部空白 */
    .block-container {
        padding-top: 1rem !important;
        padding-bottom: 1rem !important;
        max-width: 100% !important;
    }
    
    /* 4. 当侧边栏折叠时，主内容区域自动扩展 */
    section[data-testid="stSidebar"][aria-expanded="false"] ~ .main .block-container {
        max-width: 100% !important;
        padding-left: 2rem !important;
        padding-right: 2rem !important;
    }
    
    /* 5. 侧边栏样式 */
    section[data-testid="stSidebar"] {
        background: linear-gradient(180deg, #667eea 0%, #764ba2 100%);
        min-width: 300px !important;
    }
    
    section[data-testid="stSidebar"] > div:first-child {
        background: rgba(255, 255, 255, 0.98);
        border-radius: 15px;
        margin: 15px;
        padding: 20px;
    }
    
    /* 6. 全局字体与背景 */
    .stApp { 
        background: linear-gradient(135deg, #f5f7fa 0%, #c3cfe2 100%);
        font-family: 'Segoe UI', 'Microsoft YaHei', sans-serif; 
    }
    
    /* 7. 主标题样式 */
    .compact-title {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        color: white;
        font-size: 2rem;
        font-weight: 800;
        margin: -1rem -1rem 1.5rem -1rem;
        padding: 20px;
        border-radius: 10px;
        text-align: center;
        box-shadow: 0 4px 15px rgba(0,0,0,0.1);
    }
    
    /* 8. 导出区域样式 */
    .export-zone { 
        background: white; 
        padding: 25px; 
        border-radius: 15px; 
        border: 2px solid #e0e0e0;
        margin-top: 25px;
        box-shadow: 0 4px 20px rgba(0,0,0,0.08);
    }
    
    /* 9. Tabs 样式优化 */
    .stTabs [data-baseweb="tab-list"] {
        gap: 8px;
        background: #f8f9fa;
        padding: 8px;
        border-radius: 10px;
    }
    
    .stTabs [data-baseweb="tab"] {
        height: 45px;
        background: white;
        border-radius: 8px;
        padding: 0 24px;
        border: 2px solid #e0e0e0;
        font-weight: 500;
        transition: all 0.3s;
    }
    
    .stTabs [data-baseweb="tab"]:hover {
        border-color: #667eea;
        transform: translateY(-2px);
    }
    
    .stTabs [aria-selected="true"] {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        color: white !important;
        border-color: transparent;
        font-weight: 700;
    }
    
    /* 10. 侧边栏按钮样式 */
    section[data-testid="stSidebar"] .stButton>button {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        color: white;
        font-weight: 600;
        border: none;
        transition: all 0.3s;
        box-shadow: 0 2px 8px rgba(102, 126, 234, 0.3);
    }
    
    section[data-testid="stSidebar"] .stButton>button:hover {
        transform: translateY(-3px);
        box-shadow: 0 6px 20px rgba(102, 126, 234, 0.5);
    }
    
    /* 11. 主内容按钮样式 */
    .stButton>button {
        border-radius: 8px;
        font-weight: 600;
        transition: all 0.3s;
    }
    
    .stButton>button:hover {
        transform: translateY(-2px);
        box-shadow: 0 4px 12px rgba(0,0,0,0.15);
    }
    
    /* 12. 文件上传器样式 */
    .uploadedFile {
        background: #f0f2f6;
        border-radius: 10px;
        padding: 12px;
        margin: 10px 0;
        border: 1px solid #d0d0d0;
    }
    
    /* 13. 信息框样式 */
    .stInfo {
        background: linear-gradient(135deg, #e3f2fd 0%, #bbdefb 100%);
        border-left: 5px solid #2196f3;
        padding: 15px;
        border-radius: 8px;
        font-weight: 500;
    }
    
    /* 14. Metric 卡片样式 */
    [data-testid="stMetricValue"] {
        font-size: 1.8rem;
        font-weight: 700;
        color: #667eea;
    }
    
    /* 15. 文本区域样式 */
    .stTextArea textarea {
        border-radius: 10px;
        border: 2px solid #e0e0e0;
        font-family: 'Consolas', 'Monaco', monospace;
    }
    
    .stTextArea textarea:focus {
        border-color: #667eea;
        box-shadow: 0 0 0 3px rgba(102, 126, 234, 0.1);
    }
    
    /* 16. 下载按钮特殊样式 */
    .stDownloadButton>button {
        background: linear-gradient(135deg, #11998e 0%, #38ef7d 100%);
        color: white;
        font-weight: 600;
    }
    
    .stDownloadButton>button:hover {
        background: linear-gradient(135deg, #0d7968 0%, #2dd15f 100%);
    }
    
    /* 17. 分隔线样式 */
    hr {
        margin: 2rem 0;
        border: none;
        height: 2px;
        background: linear-gradient(90deg, transparent, #667eea, transparent);
    }
    
    /* 18. 响应式调整 */
    @media (max-width: 768px) {
        .compact-title {
            font-size: 1.5rem;
        }
    }
</style>
""", unsafe_allow_html=True)
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
            
            if temp_file.exists(): 
                temp_file.unlink()
            return content

        except Exception as e:
            st.error(f"❌ 转换中断: {str(e)}")
            return None

    def _preupload(self):
        res = requests.post(f"{self.base_url}/api/v2/parse/preupload", headers=self.headers)
        if res.status_code != 200: 
            raise Exception("初始化失败")
        data = res.json()
        if data["code"] != "success": 
            raise Exception("API 响应错误")
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
                res = requests.get(
                    f"{self.base_url}/api/v2/parse/status", 
                    headers=self.headers, 
                    params={"uid": uid}
                )
                data = res.json()
                if data["code"] != "success": 
                    continue
                status = data["data"]["status"]
                prog = data["data"].get("progress", 0)
                bar.progress(min(prog / 100, 0.95))
                progress_text.caption(f"⏳ 解析进度: {prog}%")
                if status == "success":
                    bar.progress(1.0)
                    progress_text.empty()
                    break
                elif status == "failed": 
                    raise Exception("AI 解析失败")
            except Exception: 
                continue

    def _trigger_export(self, uid):
        requests.post(
            f"{self.base_url}/api/v2/convert/parse", 
            headers=self.headers, 
            json={"uid": uid, "to": "md", "formula_mode": "normal", "filename": "output"}
        )

    def _wait_for_export_result(self, uid):
        while True:
            time.sleep(1)
            res = requests.get(
                f"{self.base_url}/api/v2/convert/parse/result", 
                headers=self.headers, 
                params={"uid": uid}
            )
            data = res.json()
            if data["code"] == "success" and data["data"]["status"] == "success": 
                return data["data"]["url"]
            elif data["data"]["status"] == "failed": 
                raise Exception("导出失败")

    def _download_and_extract(self, url, original_file):
        r = requests.get(url)
        base_output_dir = Path("./output").resolve()
        extract_path = base_output_dir / original_file.stem
        
        if extract_path.exists(): 
            shutil.rmtree(extract_path)
        extract_path.mkdir(parents=True, exist_ok=True)
        
        zip_path = extract_path / "result.zip"
        with open(zip_path, 'wb') as f: 
            f.write(r.content)
        
        with zipfile.ZipFile(zip_path, 'r') as z: 
            z.extractall(extract_path)
        
        md_files = list(extract_path.glob("**/*.md"))
        if not md_files: 
            raise Exception("未找到 MD 文件")
        
        with open(md_files[0], "r", encoding="utf-8") as f: 
            content = f.read()
        
        return content, extract_path

class FormatConverter:
    @staticmethod
    def generate_epub(markdown_text, work_dir, output_filename="output.epub"):
        """生成 EPUB 电子书，确保图片正确嵌入"""
        if not work_dir or not os.path.exists(work_dir):
            st.error("⚠️ 工作目录丢失，无法生成含图片的文档")
            return None

        temp_md_path = os.path.join(work_dir, "temp_render.md")
        output_path = os.path.join(work_dir, output_filename)
        
        # 保存 Markdown 文件
        with open(temp_md_path, "w", encoding="utf-8") as f:
            f.write(markdown_text)
            
        try:
            # 检查 Pandoc 是否安装
            subprocess.run(
                ["pandoc", "-v"], 
                stdout=subprocess.PIPE, 
                stderr=subprocess.PIPE,
                check=True
            )
            
            # Pandoc 转换命令（兼容旧版本）
            cmd = [
                "pandoc", 
                "temp_render.md",
                "-o", output_filename,
                "--toc",                              # 生成目录
                "--standalone",                        # 独立文档
                "--self-contained",                    # 旧版本使用这个选项嵌入资源
                "--resource-path=.",                   # 设置资源搜索路径
                "--metadata", "title=转换文档",
                "--metadata", "lang=zh-CN",           # 中文语言设置
            ]
            
            # 在工作目录中执行，确保相对路径的图片能被找到
            result = subprocess.run(
                cmd, 
                cwd=work_dir, 
                check=True, 
                capture_output=True,
                text=True
            )
            
            return output_path
            
        except subprocess.CalledProcessError as e:
            st.error(f"❌ Pandoc 转换失败 (退出码 {e.returncode}):\n```\n{e.stderr}\n```")
            return None
        except FileNotFoundError:
            st.error("❌ 系统未安装 Pandoc，无法生成 EPUB。请先安装 Pandoc。")
            return None
        except Exception as e:
            st.error(f"❌ 生成 EPUB 时发生错误: {str(e)}")
            return None

    @staticmethod
    def generate_docx(markdown_text, work_dir, output_filename="output.docx"):
        """生成 Word 文档"""
        if not work_dir or not os.path.exists(work_dir): 
            st.error("⚠️ 工作目录丢失")
            return None
        
        temp_md_path = os.path.join(work_dir, "temp_render.md")
        output_path = os.path.join(work_dir, output_filename)
        
        with open(temp_md_path, "w", encoding="utf-8") as f:
            f.write(markdown_text)
            
        try:
            # 兼容旧版本的命令
            cmd = [
                "pandoc", 
                "temp_render.md", 
                "-o", output_filename,
                "--resource-path=.",                   # 资源路径
                "--standalone",                        # 独立文档
            ]
            
            result = subprocess.run(
                cmd, 
                cwd=work_dir, 
                check=True, 
                capture_output=True,
                text=True
            )
            return output_path
        except subprocess.CalledProcessError as e:
            st.error(f"❌ Word 生成失败 (退出码 {e.returncode}):\n```\n{e.stderr}\n```")
            return None
        except Exception as e:
            st.error(f"❌ Word 生成失败: {str(e)}")
            return None

def process_images_for_preview(md_content, work_dir):
    """将 Markdown 中的本地图片转为 Base64 以供预览"""
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
                    # 判断图片类型
                    mime_type = "image/png"
                    if image_path.lower().endswith(('.jpg', '.jpeg')):
                        mime_type = "image/jpeg"
                    elif image_path.lower().endswith('.gif'):
                        mime_type = "image/gif"
                    elif image_path.lower().endswith('.svg'):
                        mime_type = "image/svg+xml"
                    
                    return f"![{alt_text}](data:{mime_type};base64,{b64_string})"
            except Exception:
                pass
        return match.group(0)

    pattern = r'!\[(.*?)\]\((.*?)\)'
    return re.sub(pattern, replace_image, md_content)

def get_pdf_page_count(file_bytes):
    """获取 PDF 页数"""
    try:
        from io import BytesIO
        reader = pypdf.PdfReader(BytesIO(file_bytes))
        return len(reader.pages)
    except: 
        return 0

def display_pdf(file_bytes):
    """显示 PDF 预览"""
    if file_bytes is None:
        st.info("💡 当前模式下无 PDF 原文预览")
        return
    try:
        pdf_viewer(input=file_bytes, width=700, height=750)
    except Exception as e:
        st.error(f"❌ PDF 组件加载失败: {str(e)}")

# --- 5. 主界面布局 ---

# 页面标题
st.markdown('<div class="compact-title">📚 夷卓汇智能转档平台</div>', unsafe_allow_html=True)

# === 侧边栏 ===
with st.sidebar:
    st.markdown("### ⚙️ 控制面板")
    
    # API Key 配置
    with st.expander("🔑 密钥配置", expanded=True):
        try: 
            default_key = st.secrets.get("DOC2X_API_KEY", "")
        except: 
            default_key = ""
        api_key = st.text_input(
            "API Key", 
            value=default_key, 
            type="password", 
            help="输入您的 Doc2X API 密钥"
        )

    st.markdown("---")
    
    # 模式选择
    st.markdown("### 📂 转换模式")
    mode = st.radio(
        "选择转换模式",
        ["📄 PDF 转电子书", "📝 Markdown 转电子书"],
        label_visibility="collapsed"
    )
    
    st.markdown("---")
    
    # 文件上传
    st.markdown("### 📤 上传文件")
    
    if mode == "📄 PDF 转电子书":
        uploaded_file = st.file_uploader(
            "选择 PDF 文件", 
            type=["pdf"], 
            help="支持最大 50MB 的 PDF 文件"
        )
        start_btn = st.button(
            "🚀 开始转换", 
            type="primary", 
            use_container_width=True
        )
    else:
        uploaded_file = st.file_uploader(
            "选择 Markdown 文件", 
            type=["md", "markdown"],
            help="上传 .md 或 .markdown 文件"
        )
        start_btn = st.button(
            "📂 加载文件", 
            type="primary", 
            use_container_width=True
        )
    
    # 使用说明
    st.markdown("---")
    with st.expander("ℹ️ 使用说明"):
        st.markdown("""
        **PDF 转电子书模式：**
        1. 输入 API Key
        2. 上传 PDF 文件
        3. 点击"开始转换"
        4. AI 智能解析文档
        5. 预览并编辑内容
        6. 导出为 EPUB/Word
        
        **Markdown 转电子书模式：**
        1. 上传 Markdown 文件
        2. 预览渲染效果
        3. 编辑源码（可选）
        4. 导出为 EPUB/Word
        
        **提示：** EPUB 和 Word 导出会自动嵌入图片
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
                st.success("✅ 转换成功！内容已加载")
                st.rerun()
    else:
        # Markdown 模式
        temp_work = Path("./output/temp_md_upload").resolve()
        if temp_work.exists(): 
            shutil.rmtree(temp_work)
        temp_work.mkdir(parents=True, exist_ok=True)
        
        content = uploaded_file.read().decode('utf-8')
        st.session_state.md_content = content
        st.session_state.pdf_bytes = None
        st.session_state.page_count = 0
        st.session_state.work_dir = str(temp_work)
        st.success("✅ Markdown 文件加载成功！")
        st.rerun()

# === 结果展示区 ===
if st.session_state.md_content:
    # 状态信息栏
    col_stat1, col_stat2, col_stat3 = st.columns([1, 1, 2])
    with col_stat1: 
        st.metric("📄 PDF 页数", st.session_state.page_count if st.session_state.page_count > 0 else "N/A")
    with col_stat2: 
        st.metric("📝 字符总数", f"{len(st.session_state.md_content):,}")
    with col_stat3:
        st.metric("📁 文件名", st.session_state.file_name)
    
    st.markdown("---")
    
    # 双栏布局：左侧 PDF，右侧编辑器
    col_left, col_right = st.columns([1, 1], gap="large")
    
    with col_left:
        st.markdown("#### 📄 原始文档预览")
        display_pdf(st.session_state.pdf_bytes)
    
    with col_right:
        st.markdown("#### ✍️ 内容编辑与预览")
        
        # 使用 Tabs 切换预览和编辑
        tab_preview, tab_edit = st.tabs(["👁️ 渲染预览 (含图片)", "📝 Markdown 源码编辑"])
        
        with tab_preview:
            # 将图片转为 Base64 以供预览
            preview_content = process_images_for_preview(
                st.session_state.md_content, 
                st.session_state.work_dir
            )
            # 使用容器显示，添加滚动
            with st.container(height=750):
                st.markdown(preview_content, unsafe_allow_html=True)
            
        with tab_edit:
            # 编辑模式
            edited_content = st.text_area(
                "编辑 Markdown 源码", 
                value=st.session_state.md_content, 
                height=700, 
                label_visibility="collapsed",
                help="在此处编辑 Markdown 内容，支持所有标准 Markdown 语法"
            )
            if edited_content != st.session_state.md_content:
                st.session_state.md_content = edited_content
                st.info("💡 内容已更新，切换到预览查看效果")

    # 导出中心
    st.markdown('<div class="export-zone">', unsafe_allow_html=True)
    st.markdown("### 📥 导出中心")
    
    exp_c1, exp_c2, exp_c3 = st.columns(3)
    
    # 下载 Markdown
    with exp_c1:
        st.download_button(
            label="📝 下载 Markdown 源码",
            data=st.session_state.md_content,
            file_name=f"{st.session_state.file_name}.md",
            mime="text/markdown",
            use_container_width=True,
            help="下载编辑后的 Markdown 源码"
        )

    # 生成 Word
    with exp_c2:
        if st.button("🟦 生成 Word 文档", use_container_width=True, help="转换为 .docx 格式"):
            with st.spinner("🔄 正在生成 Word 文档..."):
                docx_path = FormatConverter.generate_docx(
                    st.session_state.md_content,
                    st.session_state.work_dir,
                    f"{st.session_state.file_name}.docx"
                )
                if docx_path and os.path.exists(docx_path):
                    with open(docx_path, "rb") as f:
                        st.download_button(
                            label="⬇️ 点击下载 Word",
                            data=f,
                            file_name=os.path.basename(docx_path),
                            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                            key="dl_docx",
                            use_container_width=True
                        )
                    st.success("✅ Word 文档生成成功！")

    # 生成 EPUB
    with exp_c3:
        if st.button("📖 生成 EPUB 电子书", use_container_width=True, help="转换为 .epub 格式"):
            with st.spinner("🔄 正在生成 EPUB 电子书..."):
                epub_path = FormatConverter.generate_epub(
                    st.session_state.md_content,
                    st.session_state.work_dir,
                    f"{st.session_state.file_name}.epub"
                )
                if epub_path and os.path.exists(epub_path):
                    with open(epub_path, "rb") as f:
                        st.download_button(
                            label="⬇️ 点击下载 EPUB",
                            data=f,
                            file_name=os.path.basename(epub_path),
                            mime="application/epub+zip",
                            key="dl_epub",
                            use_container_width=True
                        )
                    st.success("✅ EPUB 电子书生成成功！")
    
    st.markdown('</div>', unsafe_allow_html=True)

else:
    # 欢迎页面
    st.markdown("""
    <div style="text-align: center; padding: 100px 20px; color: #95a5a6;">
        <div style="font-size: 100px; margin-bottom: 30px;">📂</div>
        <h2 style="color: #2c3e50; font-weight: 700;">欢迎使用夷卓汇智能转档平台</h2>
        <p style="font-size: 20px; margin-top: 25px; color: #7f8c8d;">
            👈 请在左侧侧边栏选择转换模式并上传文件
        </p>
        <div style="margin-top: 50px; font-size: 18px; color: #95a5a6;">
            <p>✨ 支持 PDF 智能识别 | 📝 Markdown 编辑 | 📖 EPUB/Word 导出</p>
        </div>
    </div>
    """, unsafe_allow_html=True)

# 页脚
st.markdown("---")
st.markdown(
    """
    <div style="text-align: center; color: #999; font-size: 14px; padding: 20px 0;">
        <p>夷卓汇智能转档平台 v2.0 | 让文档转换更简单高效</p>
        <p style="margin-top: 10px;">Powered by YZHAI</p>
    </div>
    """,
    unsafe_allow_html=True
)


