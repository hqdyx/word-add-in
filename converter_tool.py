import streamlit as st
import subprocess
import tempfile
import os
from pathlib import Path
import shutil

class FormatConversionTool:
    @staticmethod
    def run_conversion(uploaded_file, target_format):
        """执行转换逻辑"""
        # 创建临时目录用于处理
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            
            # 1. 保存上传的文件
            original_filename = uploaded_file.name
            source_path = temp_path / original_filename
            with open(source_path, "wb") as f:
                f.write(uploaded_file.getbuffer())
            
            # 2. 构建输出路径
            # 获取不带后缀的文件名
            stem_name = source_path.stem
            output_filename = f"{stem_name}.{target_format}"
            output_path = temp_path / output_filename
            
            # 3. 构建 Pandoc 命令
            # 基础命令
            cmd = ["pandoc", str(source_path), "-o", str(output_path)]
            
            # 针对不同格式的优化参数
            if target_format == "epub":
                # 生成 epub 时增加独立文件标记和元数据处理
                cmd.extend(["--standalone", "--metadata", f"title={stem_name}"])
            elif target_format == "docx":
                cmd.extend(["--standalone"])
            elif target_format == "md":
                # 转为 markdown 时使用 gfm (GitHub Flavored Markdown) 或标准 markdown
                cmd.extend(["-t", "markdown", "--wrap=none"]) 
                # --wrap=none 防止 pandoc 强制换行
            
            # 4. 执行命令
            try:
                subprocess.run(cmd, check=True, capture_output=True, text=True)
            except subprocess.CalledProcessError as e:
                return None, f"Pandoc 转换错误: {e.stderr}"
            except FileNotFoundError:
                return None, "未找到 Pandoc，请确保系统已安装 Pandoc。"
            
            # 5. 读取结果文件
            if output_path.exists():
                with open(output_path, "rb") as f:
                    return f.read(), None
            else:
                return None, "转换失败，未生成输出文件。"

def render_converter_ui(mode="to_epub"):
    """
    根据模式渲染不同的转换界面
    mode: "to_epub" (Word/MD -> Epub) | "to_md" (Epub -> MD)
    """
    if mode == "to_epub":
        st.header("📘 Word/Markdown 转 EPUB")
        st.caption("将文档转换为电子书格式")
        allowed_types = ["docx", "md"]
        target_format = "epub"
        btn_label = "🚀 开始转换 (生成 .epub)"
    else:
        st.header("📗 EPUB 转 Markdown")
        st.caption("将电子书还原为 Markdown 源码")
        allowed_types = ["epub"]
        target_format = "md"
        btn_label = "🚀 开始转换 (生成 .md)"

    with st.container():
        # 1. 更加具体的上传提示
        uploaded_file = st.file_uploader(
            f"上传源文件 (支持 {', '.join(allowed_types)})", 
            type=allowed_types,
            key=f"uploader_{mode}"  # 关键：使用不同key防止切换按钮时状态残留
        )
        
        if uploaded_file:
            file_ext = Path(uploaded_file.name).suffix.lower().replace(".", "")
            
            st.divider()
            col1, col2 = st.columns([1, 3])
            with col1:
                st.info(f"📄 源格式: {file_ext}")
            with col2:
                st.success(f"🎯 目标格式: {target_format}")

            # 2. 转换按钮
            if st.button(btn_label, type="primary", use_container_width=True):
                with st.spinner("正在转换中..."):
                    result_bytes, error = FormatConversionTool.run_conversion(uploaded_file, target_format)
                    
                    if error:
                        st.error(error)
                    else:
                        st.success("✅ 转换成功！")
                        
                        # 3. 下载按钮
                        new_filename = f"{Path(uploaded_file.name).stem}.{target_format}"
                        st.download_button(
                            label=f"📥 下载 {new_filename}",
                            data=result_bytes,
                            file_name=new_filename,
                            mime="application/octet-stream",
                            type="primary"
                        )
