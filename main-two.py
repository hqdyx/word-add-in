import streamlit as st
import os
import time
import requests
import zipfile
import shutil
import subprocess
import tempfile
import re
from pathlib import Path
from datetime import datetime
from enum import Enum
import threading
from queue import Queue
import concurrent.futures  # ⭐ 新增：并发库

# 引入比对模块
try:
    from comparator import DocComparator
except ImportError:
    DocComparator = None

# 尝试导入 PyPDF
try:
    import pypdf
    PYPDF_AVAILABLE = True
except ImportError:
    PYPDF_AVAILABLE = False

# =========================================================
# 状态枚举
# =========================================================
class FileStatus(Enum):
    PENDING = "待处理"
    PROCESSING = "处理中"
    COMPLETED = "已完成"
    FAILED = "失败"

# =========================================================
# 批量文件管理器
# =========================================================
class BatchFileManager:
    def __init__(self):
        if "batch_files" not in st.session_state:
            st.session_state.batch_files = []
    
    def add_files(self, uploaded_files):
        for file in uploaded_files:
            file_info = {
                "id": f"{file.name}_{datetime.now().timestamp()}",
                "name": file.name,
                "size": file.size,
                "status": FileStatus.PENDING.value,
                "upload_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "file_obj": file,
                "error_msg": None,
                "result_path": None
            }
            st.session_state.batch_files.append(file_info)
    
    def get_files_by_status(self, status):
        return [f for f in st.session_state.batch_files if f["status"] == status]
    
    def update_file_status(self, file_id, status, error_msg=None, result_path=None):
        for file in st.session_state.batch_files:
            if file["id"] == file_id:
                file["status"] = status
                if error_msg:
                    file["error_msg"] = error_msg
                if result_path:
                    file["result_path"] = result_path
                break
    
    def remove_file(self, file_id):
        st.session_state.batch_files = [
            f for f in st.session_state.batch_files if f["id"] != file_id
        ]
    
    def clear_completed(self):
        st.session_state.batch_files = [
            f for f in st.session_state.batch_files 
            if f["status"] != FileStatus.COMPLETED.value
        ]

# =========================================================
# 1. Doc2X API 客户端 (⭐ 修改：增加 silent 参数支持多线程)
# =========================================================
class Doc2XPDFClient:
    def __init__(self, api_key):
        self.api_key = api_key
        self.base_url = "https://v2.doc2x.noedgeai.com"
        self.headers = {"Authorization": f"Bearer {api_key}"}

    def process(self, file_path, silent=False):
        uid, upload_url = self._preupload(silent)
        self._upload_file(file_path, upload_url, silent)
        self._wait_for_parsing(uid, silent)
        self._trigger_export(uid, silent)
        download_url = self._wait_for_export_result(uid)
        return self._download_and_extract(download_url, file_path, silent)

    def _preupload(self, silent=False):
        if not silent: st.toast("1. 请求上传链接...", icon="☁️")
        res = requests.post(f"{self.base_url}/api/v2/parse/preupload", headers=self.headers)
        if res.status_code != 200: raise Exception(f"预上传失败: {res.text}")
        data = res.json()
        if data["code"] != "success": raise Exception(str(data))
        return data["data"]["uid"], data["data"]["url"]

    def _upload_file(self, file_path, upload_url, silent=False):
        if not silent: st.toast("2. 上传文件...", icon="📤")
        with open(file_path, "rb") as f:
            requests.put(upload_url, data=f)

    def _wait_for_parsing(self, uid, silent=False):
        if not silent: st.toast("3. AI 正在解析...", icon="🧠")
        
        progress_text = None
        bar = None
        if not silent:
            progress_text = st.empty()
            bar = st.progress(0)
            
        while True:
            time.sleep(1)
            try:
                res = requests.get(f"{self.base_url}/api/v2/parse/status", headers=self.headers, params={"uid": uid})
                if res.status_code != 200: continue
                data = res.json()
                if data["code"] != "success": 
                    if data.get("code") == "parse_error": raise Exception(data.get("msg"))
                    continue
                
                status = data["data"]["status"]
                prog = data["data"].get("progress", 0)
                
                if not silent and bar and progress_text:
                    bar.progress(min(prog / 100, 1.0))
                    progress_text.text(f"解析进度: {prog}%")
                
                if status == "success": 
                    if not silent and bar:
                        bar.progress(1.0)
                        progress_text.empty()
                    break
                elif status == "failed": raise Exception(data["data"].get("detail"))
            except requests.RequestException: continue

    def _trigger_export(self, uid, silent=False):
        if not silent: st.toast("4. 请求导出格式...", icon="⚙️")
        requests.post(f"{self.base_url}/api/v2/convert/parse", headers=self.headers, 
                      json={"uid": uid, "to": "md", "formula_mode": "normal", "filename": "output"})

    def _wait_for_export_result(self, uid):
        # 此处不涉及 UI，无需 silent
        while True:
            time.sleep(1)
            res = requests.get(f"{self.base_url}/api/v2/convert/parse/result", headers=self.headers, params={"uid": uid})
            if res.status_code != 200: continue
            data = res.json()
            if data["code"] == "success" and data["data"]["status"] == "success":
                return data["data"]["url"]
            elif data["data"]["status"] == "failed": raise Exception("导出失败")

    def _download_and_extract(self, url, original_file, silent=False):
        if not silent: st.toast("5. 下载资源包...", icon="📥")
        r = requests.get(url)
        extract_path = Path(f"./output/{original_file.stem}")
        if extract_path.exists(): shutil.rmtree(extract_path)
        extract_path.mkdir(parents=True, exist_ok=True)
        
        zip_path = extract_path / "result.zip"
        with open(zip_path, 'wb') as f: f.write(r.content)
        with zipfile.ZipFile(zip_path, 'r') as z: z.extractall(extract_path)
        return extract_path

# =========================================================
# 2. MinerU 在线 API 客户端 (⭐ 修改：增加 silent 参数)
# =========================================================
class MinerUOnlineClient:
    def __init__(self, api_key):
        self.api_key = api_key
        self.base_url = "https://mineru.net/api/v4"
        self.headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}"
        }

    def process(self, file_path, force_ocr=False, silent=False):
        original_file = Path(file_path)
        
        if not silent: st.toast("1. 申请上传链接...", icon="🔗")
        upload_url, batch_id = self._get_upload_url(original_file.name, force_ocr)
        
        if not silent: st.toast("2. 上传文件到解析中心...", icon="📤")
        self._upload_file(file_path, upload_url)
        
        if not silent: st.toast("3. AI 正在解析...", icon="🧠")
        download_url = self._wait_for_result(batch_id, original_file.name, silent)
        
        if not silent: st.toast("4. 下载解析结果...", icon="📥")
        output_dir = self._download_and_extract(download_url, original_file)
        
        return output_dir

    def _get_upload_url(self, filename, force_ocr=False):
        url = f"{self.base_url}/file-urls/batch"
        data = {
            "files": [{"name": filename}],
            "model_version": "vlm",
            "enable_formula": True,
            "enable_table": True,
            "force_ocr": force_ocr
        }
        try:
            res = requests.post(url, headers=self.headers, json=data, timeout=30)
            if res.status_code != 200: raise Exception(f"申请上传链接失败: HTTP {res.status_code}")
            result = res.json()
            if result["code"] != 0: raise Exception(f"解析错误: {result.get('msg', '未知错误')}")
            return result["data"]["file_urls"][0], result["data"]["batch_id"]
        except requests.RequestException as e: raise Exception(f"网络请求失败: {str(e)}")

    def _upload_file(self, file_path, upload_url):
        try:
            with open(file_path, 'rb') as f:
                res = requests.put(upload_url, data=f, timeout=300)
                if res.status_code != 200: raise Exception(f"文件上传失败: HTTP {res.status_code}")
        except requests.RequestException as e: raise Exception(f"上传文件失败: {str(e)}")

    def _wait_for_result(self, batch_id, filename, silent=False):
        url = f"{self.base_url}/extract-results/batch/{batch_id}"
        
        progress_text = None
        bar = None
        if not silent:
            progress_text = st.empty()
            bar = st.progress(0)
        
        max_wait_time = 600
        start_time = time.time()
        
        while True:
            if time.time() - start_time > max_wait_time: raise Exception("解析超时")
            time.sleep(3)
            
            try:
                res = requests.get(url, headers=self.headers, timeout=30)
                if res.status_code != 200: continue
                result = res.json()
                if result["code"] != 0: continue
                
                extract_results = result["data"]["extract_result"]
                file_result = next((r for r in extract_results if r["file_name"] == filename), None)
                if not file_result: continue
                
                state = file_result["state"]
                
                if not silent and bar and progress_text:
                    if state == "running":
                        if "extract_progress" in file_result:
                            prog = file_result["extract_progress"]
                            extracted = prog.get("extracted_pages", 0)
                            total = prog.get("total_pages", 1)
                            percent = min(0.2 + (extracted / total) * 0.6, 0.8)
                            bar.progress(percent)
                            progress_text.text(f"解析中: {extracted}/{total} 页")
                        else:
                            bar.progress(0.5)
                            progress_text.text("正在解析...")
                    elif state == "done":
                        bar.progress(1.0)
                        progress_text.empty()

                if state == "done":
                    if not silent: st.toast("✅ 解析完成！", icon="🎉")
                    return file_result["full_zip_url"]
                elif state == "failed":
                    err_msg = file_result.get("err_msg", "未知错误")
                    raise Exception(f"解析失败: {err_msg}")
                    
            except requests.RequestException: continue

    def _download_and_extract(self, download_url, original_file):
        output_dir = Path(f"./output/{original_file.stem}")
        if output_dir.exists(): shutil.rmtree(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        try:
            r = requests.get(download_url, timeout=300)
            zip_path = output_dir / "result.zip"
            with open(zip_path, 'wb') as f: f.write(r.content)
            with zipfile.ZipFile(zip_path, 'r') as z: z.extractall(output_dir)
            zip_path.unlink()
            return output_dir
        except Exception as e: raise Exception(f"下载结果失败: {str(e)}")

# =========================================================
# 3. 格式转换器 (修正路径错误)
# =========================================================
class FormatConverter:
    @staticmethod
    def save_md_content(content, path):
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)

    @staticmethod
    def get_md_file_path(folder):
        md_files = list(folder.glob("**/auto/*.md"))
        if not md_files: md_files = list(folder.glob("**/output.md"))
        if not md_files: md_files = list(folder.glob("**/*.md"))
        return md_files[0] if md_files else None

    @staticmethod
    def normalize_math_formulas(md_content):
        if not md_content: return ""
        md_content = re.sub(r'\\\(\s*', '$', md_content)
        md_content = re.sub(r'\s*\\\)', '$', md_content)
        md_content = re.sub(r'\\\[\s*', '\n$$\n', md_content)
        md_content = re.sub(r'\s*\\\]', '\n$$\n', md_content)
        return md_content

    @staticmethod
    def clean_image_captions(md_content):
        if not md_content: return ""
        return re.sub(r'!\[([^\]]*)\]\(([^\)]+)\)', r'![](\2)', md_content)

    @staticmethod
    def run_pandoc(input_file, output_file, format_type, source_filename=None, math_mode="mathml"):
        # 强制转换为绝对路径，解决路径查找问题
        input_path = Path(input_file).resolve()
        cwd = input_path.parent
        
        temp_input = None
        css_file = None 

        # 预处理 MD
        if input_path.suffix.lower() == '.md':
            with open(input_path, 'r', encoding='utf-8') as f: content = f.read()
            content = FormatConverter.normalize_math_formulas(content)
            content = FormatConverter.clean_image_captions(content)
            
            # 临时文件创建在同一目录下
            temp_input = cwd / f"temp_fix_{input_path.name}"
            with open(temp_input, 'w', encoding='utf-8') as f: f.write(content)
            # 传递给命令时使用文件名即可（因为设置了 cwd）
            target_input = temp_input.name
        else:
            target_input = input_path.name

        # 输出路径必须是绝对路径
        cmd = ["pandoc", target_input, "-o", str(output_file.resolve())]
        
        if format_type == "epub":
            title = Path(source_filename).stem if source_filename else input_path.stem
            metadata_file = cwd / "metadata.yaml"
            with open(metadata_file, "w", encoding="utf-8") as f:
                f.write(f"---\ntitle: {title}\n---\n")
            
            css_file = cwd / "epub_fix.css"
            with open(css_file, "w", encoding="utf-8") as f:
                f.write("h1, h2, h3 { page-break-before: avoid !important; break-before: avoid !important; }")

            cmd.extend([
                "--standalone", "--toc",
                # ⭐ 关键修改：使用 .resolve() 传递绝对路径
                "--metadata-file", str(metadata_file.resolve()),
                "--css", str(css_file.resolve()), 
                "-f", "markdown+tex_math_dollars"
            ])

            if math_mode == "mathml": cmd.append("--mathml")
            elif math_mode == "webtex": cmd.append("--webtex")
            elif math_mode == "mathjax": cmd.append("--mathjax")
            
        elif format_type == "docx":
            cmd.extend(["--standalone", "-f", "markdown+tex_math_dollars"])

        cmd.append("--resource-path=.")

        try:
            # 运行 Pandoc
            subprocess.run(cmd, cwd=cwd, check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError as e:
            # 打印更详细的错误信息
            raise Exception(f"Pandoc 转换失败 (路径: {cwd}): {e.stderr}")
        finally:
            # 清理临时文件
            if temp_input and temp_input.exists(): temp_input.unlink()
            if format_type == "epub":
                if metadata_file.exists(): metadata_file.unlink()
                if css_file and css_file.exists(): css_file.unlink()# ⭐ 清理 CSS

# =========================================================
# 4. 文档统计工具
# =========================================================
class DocumentStats:
    @staticmethod
    def count_pdf_pages(pdf_path):
        if not PYPDF_AVAILABLE: return None
        try:
            with open(pdf_path, 'rb') as f: return len(pypdf.PdfReader(f).pages)
        except Exception: return None
    
    @staticmethod
    def count_markdown_words(md_content):
        if not md_content: return 0, 0, 0
        md_content = re.sub(r'```[\s\S]*?```', '', md_content)
        md_content = re.sub(r'\$\$[\s\S]*?\$\$', '', md_content)
        chinese_chars = len(re.findall(r'[\u4e00-\u9fff]', md_content))
        english_words = len(re.findall(r'\b[a-zA-Z]+\b', md_content))
        return chinese_chars + english_words, chinese_chars, english_words
        
# =========================================================
# ⭐ 新增：多线程处理相关函数
# =========================================================

# =========================================================
# ⭐ 修改：单文件任务处理 (支持保持原文件名)
# =========================================================
def process_single_file_task(file_info, api_key_doc2x, api_key_mineru, force_ocr, math_mode, temp_dir):
    """单个文件的处理任务函数，运行在独立线程中"""
    result = {"success": False, "error": None, "result_path": None}
    
    try:
        # 1. 准备文件路径
        pdf_path = temp_dir / file_info['name']
        # 获取原始文件名（不含后缀），例如 "我的文档"
        original_stem = Path(file_info['name']).stem
        
        # 2. 选择引擎
        if api_key_mineru:
            client = MinerUOnlineClient(api_key_mineru)
            output_dir = client.process(pdf_path, force_ocr=force_ocr, silent=True)
        elif api_key_doc2x:
            client = Doc2XPDFClient(api_key_doc2x)
            output_dir = client.process(pdf_path, silent=True)
        else:
            raise Exception("未配置 API Key")

        # 3. 查找并重命名 Markdown 文件
        md_path = FormatConverter.get_md_file_path(output_dir)
        if not md_path:
            raise Exception("未找到 Markdown 文件")
            
        # ⭐ 核心修改：将提取出的 Markdown 重命名为原文件名
        # 使用 with_name 保持在同一目录，确保图片相对路径不中断
        new_md_path = md_path.with_name(f"{original_stem}.md")
        
        # 如果文件名不同，则重命名
        if md_path != new_md_path:
            # 如果目标文件已存在（极少情况），先删除
            if new_md_path.exists():
                new_md_path.unlink()
            md_path.rename(new_md_path)
            md_path = new_md_path # 更新变量指向新路径

        # 4. 设置输出路径 (使用原文件名)
        # 将生成的 Word 和 Epub 放在 output_dir 根目录下，方便查找
        docx_path = output_dir / f"{original_stem}.docx"
        epub_path = output_dir / f"{original_stem}.epub"
        
        # 5. 格式转换
        # 转换 Word
        FormatConverter.run_pandoc(md_path, docx_path, "docx")
        
        # 转换 Epub (带 CSS 修复)
        FormatConverter.run_pandoc(
            md_path, epub_path, "epub",
            source_filename=file_info['name'], # 传递原文件名用于元数据
            math_mode=math_mode
        )
        
        result["success"] = True
        result["result_path"] = str(output_dir)
        
    except Exception as e:
        result["error"] = str(e)
        
    return file_info['id'], result
    
# =========================================================
# ⭐ 修改：批量处理逻辑 (增加自动跳转)
# =========================================================
def process_batch_files(api_key_doc2x, api_key_mineru, force_ocr, math_mode):
    """执行批量文件处理（多线程版）"""
    manager = BatchFileManager()
    pending_files = manager.get_files_by_status(FileStatus.PENDING.value)
    
    if not pending_files:
        st.warning("没有待处理的文件")
        st.session_state.batch_processing = False
        return

    # 创建临时目录
    temp_dir = Path("./temp_uploads")
    temp_dir.mkdir(exist_ok=True)
    
    # 在主线程保存文件
    status_text = st.empty()
    status_text.text("正在准备文件...")
    
    ready_files = []
    for file_info in pending_files:
        try:
            pdf_path = temp_dir / file_info['name']
            if not pdf_path.exists():
                with open(pdf_path, "wb") as f:
                    f.write(file_info['file_obj'].getbuffer())
            ready_files.append(file_info)
            manager.update_file_status(file_info['id'], FileStatus.PROCESSING.value)
        except Exception as e:
            manager.update_file_status(file_info['id'], FileStatus.FAILED.value, error_msg=f"文件读取失败: {e}")

    # 切换视图到“处理中”
    st.session_state.batch_active_tab = "⚙️ 处理中"
    
    # 进度条
    progress_bar = st.progress(0)
    total_files = len(ready_files)
    completed_count = 0
    
    # 开始多线程处理
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        future_to_file = {
            executor.submit(
                process_single_file_task, 
                f, api_key_doc2x, api_key_mineru, force_ocr, math_mode, temp_dir
            ): f 
            for f in ready_files
        }
        
        status_text.text(f"🚀 正在并发处理 {total_files} 个文件...")
        
        for future in concurrent.futures.as_completed(future_to_file):
            file_id, res = future.result()
            completed_count += 1
            progress_bar.progress(completed_count / total_files)
            
            if res["success"]:
                manager.update_file_status(file_id, FileStatus.COMPLETED.value, result_path=res["result_path"])
            else:
                manager.update_file_status(file_id, FileStatus.FAILED.value, error_msg=res["error"])
    
    status_text.success("🎉 批量处理完成！")
    time.sleep(1) 
    
    # ⭐ 核心修改：处理完成后自动跳转到“已完成”标签
    st.session_state.batch_processing = False
    st.session_state.batch_active_tab = "✅ 已完成" 
    st.rerun()

# =========================================================
# ⭐ 修改：UI 渲染 (改用 Radio 实现可控标签页，紧凑布局)
# =========================================================
def render_batch_processing_ui():
    st.header("📦 批量文档处理")
    manager = BatchFileManager()
    
    # 初始化标签页状态
    if "batch_active_tab" not in st.session_state:
        st.session_state.batch_active_tab = "⏳ 待处理"

    # 上传区域
    with st.expander("📤 上传文件", expanded=len(st.session_state.batch_files) == 0):
        uploaded_files = st.file_uploader(
            "选择 PDF 文件（可多选）", type=["pdf"], accept_multiple_files=True, key="batch_uploader"
        )
        if uploaded_files and st.button("➕ 添加到处理列表"):
            manager.add_files(uploaded_files)
            st.success(f"已添加 {len(uploaded_files)} 个文件")
            st.rerun()
    
    if not st.session_state.batch_files:
        st.info("暂无文件，请上传 PDF 文件开始批量处理")
        return
    
    # 顶部统计与操作栏
    col_stat, col_act = st.columns([2, 1])
    
    with col_stat:
        # 使用简单的文本统计，比 metric 更节省空间
        total = len(st.session_state.batch_files)
        pending = len(manager.get_files_by_status(FileStatus.PENDING.value))
        completed = len(manager.get_files_by_status(FileStatus.COMPLETED.value))
        st.markdown(f"**总计**: {total} | **待处理**: {pending} | **已完成**: {completed}")

    with col_act:
        c1, c2, c3 = st.columns(3)
        if pending > 0:
            if c1.button("🚀 开始", type="primary", use_container_width=True):
                st.session_state.batch_processing = True
                st.rerun()
        if completed > 0:
            if c2.button("🧹 清除", help="清除已完成任务", use_container_width=True):
                manager.clear_completed()
                st.rerun()
        if c3.button("🗑️ 清空", help="清空所有任务", use_container_width=True):
            st.session_state.batch_files = []
            st.rerun()
            
    st.divider()
    
    # ⭐ 使用 Radio 替代 Tabs 以实现程序化跳转
    tabs = ["⏳ 待处理", "⚙️ 处理中", "✅ 已完成", "❌ 失败"]
    # 确保当前状态在选项中，防止报错
    if st.session_state.batch_active_tab not in tabs:
        st.session_state.batch_active_tab = tabs[0]
        
    selected_tab = st.radio(
        "查看分类:", 
        tabs, 
        horizontal=True, 
        key="batch_active_tab", # 绑定到 session_state
        label_visibility="collapsed"
    )
    
    # 根据选择渲染列表
    if selected_tab == "⏳ 待处理":
        render_file_list(manager.get_files_by_status(FileStatus.PENDING.value), manager)
    elif selected_tab == "⚙️ 处理中":
        render_file_list(manager.get_files_by_status(FileStatus.PROCESSING.value), manager)
    elif selected_tab == "✅ 已完成":
        render_file_list(manager.get_files_by_status(FileStatus.COMPLETED.value), manager, show_download=True)
    elif selected_tab == "❌ 失败":
        render_file_list(manager.get_files_by_status(FileStatus.FAILED.value), manager, show_error=True)

def render_file_list(files, manager, show_download=False, show_error=False):
    """渲染文件列表（紧凑版）"""
    if not files:
        st.info("此分类下暂无文件")
        return
    
    # 表头
    h1, h2, h3, h4 = st.columns([3, 1.5, 3.5, 0.5])
    h1.caption("文件名")
    h2.caption("状态")
    if show_download: h3.caption("下载结果")
    
    for file in files:
        with st.container():
            # 调整列宽比例，让下载按钮区域更宽
            c1, c2, c3, c4 = st.columns([3, 1.5, 3.5, 0.5])
            
            with c1:
                st.markdown(f"**{file['name']}**")
                st.caption(f"{file['size'] / 1024:.1f} KB")
            
            with c2: 
                st.write(f"{file['status']}")
            
            with c3:
                # ⭐ 紧凑的下载按钮组 + Markdown 下载支持
                if show_download and file['result_path']:
                    res_dir = Path(file['result_path'])
                    d_files = list(res_dir.glob("*.docx"))
                    e_files = list(res_dir.glob("*.epub"))
                    m_files = list(res_dir.glob("*.md")) # 查找 MD 文件
                    
                    # 使用内部列将按钮并排
                    # 如果有文件，显示对应的按钮（使用 icon 节省空间）
                    cols = st.columns(3) # Word, Epub, MD 三个位置
                    
                    if d_files:
                        with open(d_files[0], "rb") as f:
                            cols[0].download_button(
                                "Word", f, file_name=d_files[0].name, 
                                key=f"dd_{file['id']}", use_container_width=True
                            )
                    if e_files:
                        with open(e_files[0], "rb") as f:
                            cols[1].download_button(
                                "Epub", f, file_name=e_files[0].name, 
                                key=f"de_{file['id']}", use_container_width=True
                            )
                    if m_files:
                        with open(m_files[0], "rb") as f:
                            cols[2].download_button(
                                "MD", f, file_name=m_files[0].name, 
                                key=f"dm_{file['id']}", use_container_width=True
                            )
            
            with c4:
                if st.button("✕", key=f"del_{file['id']}", help="移除"):
                    manager.remove_file(file['id'])
                    st.rerun()
            
            if show_error and file['error_msg']:
                st.error(f"❌ {file['error_msg']}")
            
            st.divider()

def load_file_to_single_mode(file_info):
    result_dir = Path(file_info['result_path'])
    md_path = FormatConverter.get_md_file_path(result_dir)
    pdf_files = list(Path("./temp_uploads").glob(file_info['name']))
    if not md_path or not pdf_files:
        st.error("文件缺失，无法编辑")
        return
    
    with open(md_path, "r", encoding="utf-8") as f: content = f.read()
    st.session_state.work_paths = {"pdf": str(pdf_files[0]), "md": str(md_path.resolve()), "dir": str(result_dir.resolve())}
    st.session_state.current_md_content = content
    st.session_state.work_mode = "single"
    st.session_state.step = "editing"
    st.session_state.from_batch_file_id = file_info['id']

# =========================================================
# 5. Main 主程序
# =========================================================
def main():
    st.set_page_config(page_title="夷卓汇文档工作台", layout="wide")
    st.title("🛠️ 夷卓汇文档工作台")

    # 初始化状态
    if "step" not in st.session_state: st.session_state.step = "upload"
    if "current_md_content" not in st.session_state: st.session_state.current_md_content = ""
    if "work_paths" not in st.session_state: st.session_state.work_paths = {}
    if "doc_stats" not in st.session_state: st.session_state.doc_stats = {}
    if "batch_processing" not in st.session_state: st.session_state.batch_processing = False
    if "work_mode" not in st.session_state: st.session_state.work_mode = "single"
    if "batch_files" not in st.session_state: st.session_state.batch_files = []

    # 侧边栏
    with st.sidebar:
        st.header("⚙️ 设置")
        api_key_doc2x = st.text_input("API Key (标准引擎)", type="password")
        api_key_mineru = st.text_input("API Key (期刊增强)", type="password")
        force_ocr = st.checkbox("🔍 强制 OCR", value=False)
        math_mode = st.radio("数学公式", ["mathml", "webtex", "mathjax"])
        st.session_state.math_mode = math_mode
        st.divider()
        if st.button("🔄 重置"):
            st.session_state.clear()
            st.rerun()

    # 模式选择
    c1, c2 = st.columns(2)
    with c1:
        if st.button("📄 单文件处理", type="primary" if st.session_state.work_mode == "single" else "secondary", use_container_width=True):
            st.session_state.work_mode = "single"
            st.rerun()
    with c2:
        if st.button("📦 批量处理", type="primary" if st.session_state.work_mode == "batch" else "secondary", use_container_width=True):
            st.session_state.work_mode = "batch"
            st.rerun()
    
    st.divider()

    # 路由
    if st.session_state.work_mode == "batch":
        if st.session_state.batch_processing:
            process_batch_files(api_key_doc2x, api_key_mineru, force_ocr, math_mode)
        else:
            render_batch_processing_ui()
# ========== 单文件处理模式 ==========
    else:
        # 阶段 1: 上传
        if st.session_state.step == "upload":
            st.info("步骤 1/3: 上传 PDF 进行智能解析")
            uploaded_file = st.file_uploader("选择 PDF 文件", type=["pdf"])

            if uploaded_file and st.button("🚀 开始解析"):
                # 获取左侧栏选择的引擎
                if api_key_mineru:
                    selected_engine = "mineru"
                elif api_key_doc2x:
                    selected_engine = "doc2x"
                else:
                    st.error("请先在左侧填写 API Key（标准 或 期刊增强）")
                    return
                
                try:
                    temp_dir = Path("./temp_uploads")
                    temp_dir.mkdir(exist_ok=True)
                    pdf_path = (temp_dir / uploaded_file.name).resolve()
                    with open(pdf_path, "wb") as f:
                        f.write(uploaded_file.getbuffer())

                    pdf_pages = DocumentStats.count_pdf_pages(pdf_path)

                    # 执行解析 (注意：单文件模式下 silent=False，显示进度条)
                    if selected_engine == "mineru":
                        client = MinerUOnlineClient(api_key_mineru)
                        output_dir = client.process(pdf_path, force_ocr, silent=False)
                    else:
                        client = Doc2XPDFClient(api_key_doc2x)
                        output_dir = client.process(pdf_path, silent=False)
                    
                    # 获取并重命名 Markdown 文件 (保持文件名一致性)
                    md_path = FormatConverter.get_md_file_path(output_dir)
                    if not md_path:
                        raise Exception("未找到 Markdown 文件")
                    
                    # ⭐ 像批量模式一样，重命名 markdown 文件
                    original_stem = Path(uploaded_file.name).stem
                    new_md_path = md_path.with_name(f"{original_stem}.md")
                    if md_path != new_md_path:
                        if new_md_path.exists(): new_md_path.unlink()
                        md_path.rename(new_md_path)
                        md_path = new_md_path

                    with open(md_path, "r", encoding="utf-8") as f:
                        content = f.read()

                    total_words, chinese_chars, english_words = DocumentStats.count_markdown_words(content)

                    # 更新 Session State
                    st.session_state.work_paths = {
                        "pdf": str(pdf_path),
                        "md": str(md_path.resolve()),
                        "dir": str(output_dir.resolve())
                    }
                    st.session_state.current_md_content = content
                    
                    st.session_state.doc_stats = {
                        "pdf_pages": pdf_pages,
                        "total_words": total_words,
                        "chinese_chars": chinese_chars,
                        "english_words": english_words
                    }
                    
                    st.session_state.step = "editing"
                    st.rerun()
                    
                except Exception as e:
                    st.error(f"处理失败: {str(e)}")

        # 阶段 2: 编辑
        elif st.session_state.step == "editing":
            paths = st.session_state.work_paths
            stats = st.session_state.doc_stats
            
            # 如果来自批量处理，显示返回按钮
            if "from_batch_file_id" in st.session_state:
                if st.button("⬅️ 返回批量处理列表"):
                    st.session_state.work_mode = "batch"
                    st.session_state.step = "upload"
                    # 清理标记，避免逻辑混淆
                    del st.session_state.from_batch_file_id
                    st.rerun()
                st.divider()
            
            # 统计栏
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("📄 PDF 页数", f"{stats.get('pdf_pages', '未知')}")
            c2.metric("📊 总字数", f"{stats.get('total_words', 0):,}")
            c3.metric("🇨🇳 中文字符", f"{stats.get('chinese_chars', 0):,}")
            c4.metric("🇬🇧 英文单词", f"{stats.get('english_words', 0):,}")
            
            st.divider()
            
            col1, col2 = st.columns([3, 1])
            with col1: st.subheader("步骤 2/3: 校对与编辑")
            with col2:
                if st.button("💾 完成校对，生成文档", type="primary", use_container_width=True):
                    st.session_state.step = "generating"
                    st.rerun()

            # 编辑器渲染
            if DocComparator:
                cmp = DocComparator()
                cmp.render_editor_ui(
                    paths["pdf"],
                    st.session_state.current_md_content,
                    image_root=paths["dir"]
                )
                if "editor_textarea" in st.session_state:
                    st.session_state.current_md_content = st.session_state.editor_textarea
            else:
                st.session_state.current_md_content = st.text_area(
                    "Markdown 内容",
                    st.session_state.current_md_content,
                    height=800
                )

        # 阶段 3: 导出
        elif st.session_state.step == "generating":
            st.subheader("步骤 3/3: 导出文档")
            paths = st.session_state.work_paths
            md_path = Path(paths["md"])
            output_dir = Path(paths["dir"])
            pdf_path = Path(paths["pdf"])
            original_stem = pdf_path.stem # 使用原文件名
            
            st.write("1. 保存最终内容...")
            FormatConverter.save_md_content(st.session_state.current_md_content, md_path)
            
            try:
                # 使用统一的文件名生成
                docx_path = output_dir / f"{original_stem}.docx"
                epub_path = output_dir / f"{original_stem}.epub"

                st.write("2. 生成 Word 文档...")
                FormatConverter.run_pandoc(md_path, docx_path, "docx")
                
                st.write(f"3. 生成 EPUB 电子书 (模式: {st.session_state.math_mode})...")
                FormatConverter.run_pandoc(
                    md_path, epub_path, "epub",
                    source_filename=pdf_path.name,
                    math_mode=st.session_state.math_mode
                )
                
                st.success("✅ 生成完成！")
                
                # 下载按钮区域
                c1, c2, c3, c4 = st.columns(4)
                with open(docx_path, "rb") as f:
                    c1.download_button("📘 下载 Word", f, file_name=docx_path.name)
                with open(epub_path, "rb") as f:
                    c2.download_button("📗 下载 EPUB", f, file_name=epub_path.name)
                with open(md_path, "rb") as f:
                    c3.download_button("📝 下载 Markdown", f, file_name=md_path.name)
                
                if c4.button("⬅️ 返回继续修改"):
                    st.session_state.step = "editing"
                    st.rerun()
                
                # 如果是从批量列表来的，显示返回批量按钮
                if "from_batch_file_id" in st.session_state:
                    st.divider()
                    if st.button("📦 返回批量列表", type="secondary", use_container_width=True):
                        st.session_state.work_mode = "batch"
                        # 不删除 from_batch_file_id 以外的状态，以便保留缓存
                        st.session_state.step = "upload" # 重置单文件流程步骤
                        del st.session_state.from_batch_file_id
                        st.rerun()

            except Exception as e:
                st.error(f"转换出错: {e}")
                if st.button("重试"):
                    st.rerun()
                    
if __name__ == "__main__":
    main()   
