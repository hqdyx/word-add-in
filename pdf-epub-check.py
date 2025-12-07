import streamlit as st
import os
import time
import requests
import zipfile
import shutil
import subprocess
import base64
from pathlib import Path

# =========================================================
# 1. PDF 处理客户端
# =========================================================
class Doc2XPDFClient:
    def __init__(self, api_key):
        self.api_key = api_key
        self.base_url = "https://v2.doc2x.noedgeai.com"
        self.headers = {"Authorization": f"Bearer {api_key}"}

    def process(self, file_path):
        """PDF 全流程：预上传 -> 上传 -> 解析 -> 导出 -> 下载"""
        uid, upload_url = self._preupload()
        self._upload_file(file_path, upload_url)
        self._wait_for_parsing(uid)
        self._trigger_export(uid)
        download_url = self._wait_for_export_result(uid)
        return self._download_and_extract(download_url, file_path)

    def _preupload(self):
        st.write("1. [PDF] 请求上传链接...")
        try:
            res = requests.post(f"{self.base_url}/api/v2/parse/preupload", headers=self.headers)
            if res.status_code != 200: raise Exception(f"预上传失败: {res.text}")
            data = res.json()
            if data["code"] != "success": raise Exception(str(data))
            return data["data"]["uid"], data["data"]["url"]
        except Exception as e:
            raise Exception(f"连接服务器失败: {e}")

    def _upload_file(self, file_path, upload_url):
        st.write("2. [PDF] 上传文件到云端...")
        with open(file_path, "rb") as f:
            res = requests.put(upload_url, data=f)
            if res.status_code != 200: raise Exception("上传文件到云存储失败")

    def _wait_for_parsing(self, uid):
        st.write("3. [PDF] AI 正在分析文档布局...")
        progress_bar = st.progress(0)
        while True:
            time.sleep(2)
            try:
                res = requests.get(f"{self.base_url}/api/v2/parse/status", headers=self.headers, params={"uid": uid})
                if res.status_code != 200: continue
                data = res.json()
                if data["code"] != "success": 
                    if data.get("code") == "parse_error": raise Exception(data.get("msg"))
                    continue
                
                status = data["data"]["status"]
                prog = data["data"].get("progress", 0)
                progress_bar.progress(min(prog / 100, 1.0))
                
                if status == "success": 
                    progress_bar.progress(1.0)
                    break
                elif status == "failed": raise Exception(data["data"].get("detail"))
            except requests.RequestException:
                continue

    def _trigger_export(self, uid):
        st.write("4. [PDF] 正在请求生成 Markdown 包...")
        requests.post(f"{self.base_url}/api/v2/convert/parse", headers=self.headers, 
                      json={"uid": uid, "to": "md", "formula_mode": "normal", "filename": "output"})

    def _wait_for_export_result(self, uid):
        st.write("5. [PDF] 等待导出完成...")
        while True:
            time.sleep(2)
            res = requests.get(f"{self.base_url}/api/v2/convert/parse/result", headers=self.headers, params={"uid": uid})
            if res.status_code != 200: continue
            data = res.json()
            if data["code"] == "success" and data["data"]["status"] == "success":
                return data["data"]["url"]
            elif data["data"]["status"] == "failed": raise Exception("导出失败")

    def _download_and_extract(self, url, original_file):
        st.write("6. [PDF] 下载并解压...")
        r = requests.get(url)
        extract_path = Path(f"./output/{original_file.stem}")
        if extract_path.exists(): shutil.rmtree(extract_path)
        extract_path.mkdir(parents=True, exist_ok=True)
        
        zip_path = extract_path / "result.zip"
        with open(zip_path, 'wb') as f: f.write(r.content)
        with zipfile.ZipFile(zip_path, 'r') as z: z.extractall(extract_path)
        return extract_path


# =========================================================
# 2. 图片/强制OCR 客户端
# =========================================================
class Doc2XImageClient:
    def __init__(self, api_key):
        self.api_key = api_key
        self.base_url = "https://v2.doc2x.noedgeai.com"
        self.headers = {"Authorization": f"Bearer {api_key}"}

    def process(self, file_path):
        uid = self._submit_async(file_path)
        return self._poll_and_extract(uid, file_path)

    def _submit_async(self, file_path):
        st.write("1. [OCR] 正在提交图片任务...")
        url = f"{self.base_url}/api/v2/async/parse/img/layout"
        with open(file_path, 'rb') as f: img_data = f.read()
        res = requests.post(url, headers=self.headers, data=img_data)
        if res.status_code != 200: raise Exception(f"提交失败: {res.text}")
        data = res.json()
        if data["code"] != "success": raise Exception(f"API报错: {data}")
        return data["data"]["uid"]

    def _poll_and_extract(self, uid, original_file):
        st.write("2. [OCR] 正在进行深度识别...")
        url = f"{self.base_url}/api/v2/parse/img/layout/status"
        progress_bar = st.progress(0)
        while True:
            time.sleep(2)
            res = requests.get(url, headers=self.headers, params={"uid": uid})
            if res.status_code != 200: continue
            data = res.json()
            if data["code"] != "success":
                if data.get("code") == "parse_error": raise Exception("解析错误")
                continue
            status = data["data"].get("status")
            if status == "success":
                progress_bar.progress(1.0)
                st.write("3. [OCR] 识别成功，正在处理资源...")
                return self._handle_success_data(data["data"], original_file)
            elif status == "failed": raise Exception("图片解析失败")

    def _handle_success_data(self, data, original_file):
        extract_path = Path(f"./output/{original_file.stem}_ocr")
        if extract_path.exists(): shutil.rmtree(extract_path)
        extract_path.mkdir(parents=True, exist_ok=True)
        
        zip_base64 = data.get("convert_zip")
        if zip_base64:
            try:
                zip_content = base64.b64decode(zip_base64)
                with open(extract_path / "images.zip", "wb") as f: f.write(zip_content)
                with zipfile.ZipFile(extract_path / "images.zip", 'r') as z: z.extractall(extract_path)
            except Exception: pass
        
        full_md = ""
        for page in data.get("result", {}).get("pages", []):
            full_md += page.get("md", "") + "\n\n"
        with open(extract_path / "output.md", "w", encoding="utf-8") as f: f.write(full_md)
        return extract_path


# =========================================================
# 3. 通用格式转换 (Pandoc)
# =========================================================
class FormatConverter:
    @staticmethod
    def get_md_file(folder):
        md_files = list(folder.glob("**/output.md"))
        if not md_files: md_files = list(folder.glob("**/*.md"))
        if not md_files: raise Exception("未找到 Markdown 文件")
        return md_files[0]

    @staticmethod
    def generate_epub(md_path, output_epub_path):
        cwd = md_path.parent
        # 创建简易 CSS 样式
        css_content = """
        img { max-width: 100%; height: auto; display: block; margin: 1em auto; }
        table { width: 100%; border-collapse: collapse; margin: 1em 0; }
        th, td { border: 1px solid #ccc; padding: 6px; }
        pre { background: #f4f4f4; padding: 10px; border-radius: 5px; overflow-x: auto; }
        blockquote { border-left: 4px solid #ccc; padding-left: 10px; color: #666; }
        """
        css_path = cwd / "style.css"
        with open(css_path, "w", encoding="utf-8") as f: f.write(css_content)

        cmd = [
            "pandoc", md_path.name,
            "-o", str(output_epub_path.resolve()),
            "--resource-path=.", "--toc", "--mathml",
            f"--css={css_path.name}", "--metadata", "title=夷卓汇电子书"
        ]
        subprocess.run(cmd, cwd=cwd, check=True)
    
    @staticmethod
    def generate_docx(md_path, output_docx_path):
        """【新增】生成 DOCX 文件"""
        cwd = md_path.parent
        cmd = [
            "pandoc", md_path.name,
            "-o", str(output_docx_path.resolve()),
            "--resource-path=."
        ]
        subprocess.run(cmd, cwd=cwd, check=True)


# =========================================================
# 辅助功能：对比显示
# =========================================================
def display_pdf_vs_markdown(pdf_path, md_content):
    """【新增】左右分屏展示 PDF 和 Markdown"""
    st.markdown("### 👀 文档对比 (左: 原文 / 右: 识别结果)")
    c1, c2 = st.columns([1, 1])
    
    with c1:
        st.markdown("**PDF 原文**")
        # 使用 iframe 嵌入 PDF，需要读取为 base64
        with open(pdf_path, "rb") as f:
            base64_pdf = base64.b64encode(f.read()).decode('utf-8')
        pdf_display = f'<iframe src="data:application/pdf;base64,{base64_pdf}" width="100%" height="800" type="application/pdf"></iframe>'
        st.markdown(pdf_display, unsafe_allow_html=True)
        
    with c2:
        st.markdown("**Markdown 解析结果**")
        # 使用 text_area 显示源码，或者 st.markdown 渲染
        # 这里使用 tab 允许用户切换视图
        tab1, tab2 = st.tabs(["渲染视图", "源码视图"])
        with tab1:
            st.markdown(md_content, unsafe_allow_html=True)
        with tab2:
            st.text_area("Markdown Source", md_content, height=800)


# =========================================================
# Streamlit 主程序
# =========================================================
def main():
    st.set_page_config(page_title="夷卓汇工具集", page_icon="🛠️", layout="wide") # 开启宽屏模式方便对比
    
    st.title("🛠️ 夷卓汇工具集")
    st.subheader("智能文档转换引擎")
    
    # 模式选择
    mode = st.radio(
        "📂 请选择功能模式",
        ("PDF 文档 (AI解析)", "单张图片 (AI-OCR)", "Markdown 文档 (直接转电子书)"),
    )

    api_key = ""
    if mode in ["PDF 文档 (AI解析)", "单张图片 (AI-OCR)"]:
        st.sidebar.header("🔑 授权配置")
        api_key = st.sidebar.text_input("API Key", type="password", help="请输入您的服务密钥 (sk-xxx)")
        if not api_key:
            st.sidebar.warning("⚠️ 使用 AI 功能需要配置 API Key")
    else:
        st.sidebar.success("✅ 本地转换模式无需 API Key")

    st.markdown("---")

    uploaded_file = None
    
    if mode == "PDF 文档 (AI解析)":
        st.info("ℹ️ 智能云端解析：自动处理版面、公式和表格，保留图文结构。")
        uploaded_file = st.file_uploader("上传 PDF", type=["pdf"])
        
    elif mode == "单张图片 (AI-OCR)":
        st.info("ℹ️ 强制 OCR：对图片进行全文文本识别。")
        uploaded_file = st.file_uploader("上传图片", type=["jpg", "png", "jpeg"])
        
    elif mode == "Markdown 文档 (直接转电子书)":
        st.info("ℹ️ 本地转换：将现有的 Markdown 转换为 EPUB/DOCX。")
        st.warning("注意：如果文档中引用了本地图片，请确保图片链接是网络地址，否则生成的电子书图片将丢失。")
        uploaded_file = st.file_uploader("上传 Markdown", type=["md"])

    # 统一转换按钮
    if uploaded_file and st.button("🚀 开始处理"):
        
        if mode in ["PDF 文档 (AI解析)", "单张图片 (AI-OCR)"] and not api_key:
            st.error("请先在左侧侧边栏填入 API Key！")
            return

        temp_dir = Path("./temp_uploads")
        temp_dir.mkdir(exist_ok=True)
        save_path = temp_dir / uploaded_file.name
        
        with open(save_path, "wb") as f:
            f.write(uploaded_file.getbuffer())

        try:
            output_dir = None
            
            # 2. 分发处理逻辑
            if mode == "PDF 文档 (AI解析)":
                client = Doc2XPDFClient(api_key)
                output_dir = client.process(save_path)
                
            elif mode == "单张图片 (AI-OCR)":
                client = Doc2XImageClient(api_key)
                output_dir = client.process(save_path)
                
            elif mode == "Markdown 文档 (直接转电子书)":
                st.write("1. 正在准备本地环境...")
                output_dir = Path(f"./output/local_{save_path.stem}")
                if output_dir.exists(): shutil.rmtree(output_dir)
                output_dir.mkdir(parents=True, exist_ok=True)
                
                target_md = output_dir / uploaded_file.name
                shutil.copy(save_path, target_md)
                st.write("2. 文件已就绪，准备转换...")

            # 3. 准备文件路径
            converter = FormatConverter()
            md_file = converter.get_md_file(output_dir)
            epub_path = output_dir / f"{save_path.stem}.epub"
            docx_path = output_dir / f"{save_path.stem}.docx" # 新增 docx 路径
            
            # 4. 读取 Markdown 内容用于展示
            with open(md_file, "r", encoding="utf-8") as f:
                md_content = f.read()

            # 5. 生成电子书和文档
            st.write("📖 正在封装 EPUB 电子书...")
            converter.generate_epub(md_file, epub_path)
            
            st.write("📝 正在生成 DOCX 文档...") # 新增提示
            converter.generate_docx(md_file, docx_path) # 执行 docx 转换
            
            st.success("✅ 任务完成！")

            # 6. 对比展示 (仅在 PDF 模式下展示 PDF vs MD，其他模式展示 MD)
            st.divider()
            if mode == "PDF 文档 (AI解析)":
                display_pdf_vs_markdown(save_path, md_content)
            else:
                st.markdown("### 解析结果预览")
                st.markdown(md_content)
            
            st.divider()

            # 7. 下载区 (增加 DOCX 按钮)
            st.subheader("📥 下载结果")
            col1, col2, col3 = st.columns(3)
            
            with open(epub_path, "rb") as f:
                col1.download_button("📘 下载 EPUB 电子书", f, file_name=epub_path.name)
            
            with open(docx_path, "rb") as f:
                col2.download_button("📄 下载 Word (DOCX)", f, file_name=docx_path.name)

            if mode != "Markdown 文档 (直接转电子书)":
                with open(md_file, "rb") as f:
                    col3.download_button("📝 下载 Markdown 源码", f, file_name=md_file.name)

        except Exception as e:
            st.error(f"❌ 发生错误: {str(e)}")

if __name__ == "__main__":
    main()
