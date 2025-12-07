import streamlit as st
import requests
import os
import zipfile
import subprocess
import shutil
import time
import base64
from pathlib import Path
import pypdf  # 需要 pip install pypdf

# --- 1. 页面配置：开启宽屏模式与专业设置 ---
st.set_page_config(
    page_title="夷卓汇 - 智能文档转档平台", 
    page_icon="📚",
    layout="wide",
    initial_sidebar_state="expanded",
    menu_items={
        'About': "夷卓汇智能文档转换工具 v3.0 Professional"
    }
)

# --- 2. 专业级 UI 设计 (CSS) ---
st.markdown("""
<style>
    /* 全局字体与背景 */
    .stApp {
        background-color: #f8f9fa;
        font-family: 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
    }
    
    /* 侧边栏样式 */
    section[data-testid="stSidebar"] {
        background-color: #ffffff;
        box-shadow: 2px 0 10px rgba(0,0,0,0.05);
    }
    
    /* 标题样式 */
    h1 {
        color: #2c3e50;
        font-weight: 800 !important;
        letter-spacing: -0.5px;
    }
    h2, h3 {
        color: #34495e;
    }
    
    /* 卡片容器样式 */
    .css-card {
        background-color: white;
        padding: 20px;
        border-radius: 12px;
        box-shadow: 0 4px 6px rgba(0,0,0,0.04);
        margin-bottom: 20px;
        border: 1px solid #e9ecef;
    }
    
    /* 按钮样式优化 */
    .stButton>button {
        border-radius: 8px;
        font-weight: 600;
        transition: all 0.2s ease;
    }
    .stButton>button:hover {
        transform: translateY(-1px);
        box-shadow: 0 4px 12px rgba(0,0,0,0.1);
    }
    
    /* 状态指标样式 */
    div[data-testid="stMetricValue"] {
        color: #2980b9;
        font-size: 24px;
    }
    
    /* PDF 阅读器容器 */
    .pdf-container {
        border: 1px solid #dfe6e9;
        border-radius: 8px;
        overflow: hidden;
        box-shadow: inset 0 2px 4px rgba(0,0,0,0.05);
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
if 'processing_done' not in st.session_state:
    st.session_state.processing_done = False

# --- 4. 核心功能类 ---

class CloudConverter:
    """处理云端转换逻辑 (原 Doc2X 逻辑，已隐去名称)"""
    def __init__(self, api_key):
        self.api_key = api_key
        # API 端点保持不变，但不在界面展示
        self.base_url = "https://v2.doc2x.noedgeai.com"
        self.headers = {"Authorization": f"Bearer {api_key}"}

    def convert(self, file_obj, pdf_bytes):
        try:
            # 创建临时文件
            temp_dir = Path("./temp_uploads")
            temp_dir.mkdir(exist_ok=True)
            temp_file = temp_dir / file_obj.name
            
            with open(temp_file, "wb") as f:
                f.write(file_obj.getbuffer())
            
            st.session_state.pdf_bytes = pdf_bytes
            
            # 使用 st.status 展示漂亮的进度条
            with st.status("🚀 AI 引擎正在处理...", expanded=True) as status:
                
                # Step 1: 预上传
                st.write("📡 建立安全连接...")
                uid, upload_url = self._preupload()
                
                # Step 2: 上传
                st.write("☁️ 上传加密文档...")
                self._upload_file(temp_file, upload_url)
                
                # Step 3: 解析
                st.write("🧠 AI 深度解析文档结构与公式...")
                self._wait_for_parsing(uid)
                
                # Step 4: 导出
                st.write("📦 生成 Markdown 数据包...")
                self._trigger_export(uid)
                download_url = self._wait_for_export_result(uid)
                
                # Step 5: 下载
                st.write("⬇️ 获取最终结果...")
                content = self._download_and_extract(download_url, temp_file)
                
                status.update(label="✅ 转换完成！", state="complete", expanded=False)
            
            # 清理
            if temp_file.exists():
                temp_file.unlink()
            
            return content

        except Exception as e:
            st.error(f"❌ 转换中断: {str(e)}")
            return None

    def _preupload(self):
        try:
            res = requests.post(f"{self.base_url}/api/v2/parse/preupload", headers=self.headers)
            if res.status_code != 200: raise Exception(f"连接失败 ({res.status_code})")
            data = res.json()
            if data["code"] != "success": raise Exception("服务响应异常")
            return data["data"]["uid"], data["data"]["url"]
        except Exception as e:
            raise Exception(f"网络初始化失败: {e}")

    def _upload_file(self, file_path, upload_url):
        with open(file_path, "rb") as f:
            requests.put(upload_url, data=f)

    def _wait_for_parsing(self, uid):
        # 增加进度条显示
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
                elif status == "failed":
                    raise Exception("AI 解析失败，请检查文档是否加密或损坏")
            except Exception:
                continue

    def _trigger_export(self, uid):
        requests.post(f"{self.base_url}/api/v2/convert/parse", headers=self.headers, json={"uid": uid, "to": "md", "formula_mode": "normal", "filename": "output"})

    def _wait_for_export_result(self, uid):
        while True:
            time.sleep(1)
            res = requests.get(f"{self.base_url}/api/v2/convert/parse/result", headers=self.headers, params={"uid": uid})
            data = res.json()
            if data["code"] == "success" and data["data"]["status"] == "success":
                return data["data"]["url"]
            elif data["data"]["status"] == "failed":
                raise Exception("导出格式化失败")

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
    def generate_epub(markdown_text, output_filename="output.epub"):
        temp_md = "temp_edit.md"
        with open(temp_md, "w", encoding="utf-8") as f: f.write(markdown_text)
        
        try:
            try:
                subprocess.run(["pandoc", "-v"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            except FileNotFoundError:
                st.error("⚠️ 系统核心组件缺失: Pandoc 未安装")
                return None

            # 简单的 CSS 优化阅读体验
            css_path = "ebook.css"
            with open(css_path, "w") as f:
                f.write("body{font-family: sans-serif; line-height: 1.6;} img{max-width:100%;} h1,h2{color:#2c3e50;}")

            cmd = [
                "pandoc", temp_md, "-o", output_filename,
                "--toc", "--split-level=2",
                f"--css={css_path}", "--metadata", "title=Converted Ebook"
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                st.error(f"EPUB 生成失败: {result.stderr}")
                return None
            return output_filename
        except Exception as e:
            st.error(f"生成错误: {str(e)}")
            return None

def get_pdf_page_count(file_bytes):
    """统计 PDF 页数"""
    try:
        from io import BytesIO
        reader = pypdf.PdfReader(BytesIO(file_bytes))
        return len(reader.pages)
    except Exception:
        return 0

def display_pdf(file_bytes):
    """增强版 PDF 显示器"""
    if file_bytes is None:
        st.info("💡 暂无 PDF 预览")
        return
    
    # 将 PDF 转换为 base64
    base64_pdf = base64.b64encode(file_bytes).decode('utf-8')
    
    # 使用 embed 标签作为主要显示方式，iframe 作为备选，兼容性更好
    pdf_display = f"""
    <div class="pdf-container">
        <embed
            src="data:application/pdf;base64,{base64_pdf}"
            width="100%"
            height="800px"
            type="application/pdf"
        >
            <p>您的浏览器不支持 PDF 预览，请下载查看。</p>
        </embed>
    </div>
    """
    st.markdown(pdf_display, unsafe_allow_html=True)

# --- 5. 主界面布局 ---

# 侧边栏
with st.sidebar:
    st.title("⚙️ 控制面板")
    
    # API 设置
    with st.expander("🔑 密钥配置", expanded=True):
        try:
            default_key = st.secrets.get("DOC2X_API_KEY", "")
        except:
            default_key = ""
        api_key = st.text_input("API Key", value=default_key, type="password", help="请输入您的转换引擎密钥")

    st.markdown("---")
    
    # 模式选择
    mode = st.radio("选择模式", ["📄 PDF 转电子书", "📝 Markdown 转电子书"], index=0)
    
    st.markdown("---")
    
    # 上传区域
    if mode == "📄 PDF 转电子书":
        uploaded_file = st.file_uploader("上传文档", type=["pdf"], help="支持中文、公式混排 PDF")
        if uploaded_file:
            st.info(f"文件名: {uploaded_file.name}")
        start_btn = st.button("开始转换 ✨", type="primary", use_container_width=True)
    else:
        uploaded_file = st.file_uploader("上传 Markdown", type=["md"], help="直接上传 .md 文件")
        start_btn = st.button("加载文件 📂", type="primary", use_container_width=True)

    st.markdown("---")
    st.caption("© 2024 夷卓汇 Pro")

# 主区域
st.title("📚 夷卓汇智能转档")
st.markdown("#### 让文档阅读更自由，支持复杂排版与数学公式的完美重构")

if start_btn and uploaded_file:
    st.session_state.file_name = uploaded_file.name.rsplit('.', 1)[0]
    st.session_state.processing_done = True
    
    if mode == "📄 PDF 转电子书":
        if not api_key:
            st.error("🚫 请先在左侧输入 API Key")
        else:
            # 读取并统计页数
            uploaded_file.seek(0)
            pdf_bytes = uploaded_file.read()
            uploaded_file.seek(0)
            
            # 统计页数
            st.session_state.page_count = get_pdf_page_count(pdf_bytes)
            
            # 运行转换
            converter = CloudConverter(api_key)
            result_text = converter.convert(uploaded_file, pdf_bytes)
            
            if result_text:
                st.session_state.md_content = result_text
                st.rerun()
    else:
        # Markdown 模式
        content = uploaded_file.read().decode('utf-8')
        st.session_state.md_content = content
        st.session_state.pdf_bytes = None # 清空 PDF
        st.session_state.page_count = 0
        st.rerun()

# 结果展示区
if st.session_state.md_content:
    # 统计数据栏
    col_m1, col_m2, col_m3, col_m4 = st.columns(4)
    with col_m1:
        st.metric("文档状态", "✅ 已就绪")
    with col_m2:
        st.metric("原始页数", f"{st.session_state.page_count} 页")
    with col_m3:
        st.metric("识别字符", f"{len(st.session_state.md_content):,} 字")
    with col_m4:
        st.metric("输出格式", "EPUB 电子书")
    
    st.markdown("---")
    
    # 双栏工作台
    col_preview, col_editor = st.columns([1, 1])
    
    with col_preview:
        st.subheader("📄 原始文档预览")
        display_pdf(st.session_state.pdf_bytes)
    
    with col_editor:
        st.subheader("✍️ 内容校对与编辑")
        # 编辑器容器
        with st.container():
            edited_content = st.text_area(
                "Markdown源码", 
                value=st.session_state.md_content, 
                height=800,
                label_visibility="collapsed"
            )
            if edited_content != st.session_state.md_content:
                st.session_state.md_content = edited_content

    # 底部导出操作
    st.markdown("---")
    st.subheader("📖 导出")
    
    col_dl1, col_dl2 = st.columns([3, 1])
    with col_dl1:
        st.caption("提示：左侧的编辑内容将实时同步到电子书中。确认无误后点击生成。")
    
    with col_dl2:
        if st.button("生成最终 EPUB", type="primary", use_container_width=True):
            with st.spinner("正在打包电子书..."):
                epub_path = FormatConverter.generate_epub(
                    st.session_state.md_content,
                    f"{st.session_state.file_name}.epub"
                )
                if epub_path:
                    with open(epub_path, "rb") as f:
                        st.download_button(
                            label="⬇️ 点击下载",
                            data=f,
                            file_name=os.path.basename(epub_path),
                            mime="application/epub+zip",
                            use_container_width=True
                        )
                    st.success("电子书生成完毕！")

elif not st.session_state.processing_done:
    # 初始空状态欢迎页
    st.markdown("""
    <div style="text-align: center; padding: 60px 0; color: #95a5a6;">
        <div style="font-size: 60px; margin-bottom: 20px;">📂</div>
        <h3>请在左侧上传文件开始工作</h3>
        <p>支持 PDF 智能识别与 Markdown 直接转换</p>
    </div>
    """, unsafe_allow_html=True)
