#!/usr/bin/env python3
"""
Policy OS 一键启动脚本

用法:
    python scripts/run_policy_os.py          # 完整流程
    python scripts/run_policy_os.py --demo  # 演示模式
    python scripts/run_policy_os.py --fetch  # 仅抓取
"""

import subprocess
import sys
import os
from pathlib import Path

def run_cmd(cmd, desc):
    """运行命令并报告结果"""
    print(f"\n{'='*60}")
    print(f"{desc}")
    print(f"{'='*60}")

    result = subprocess.run(
        cmd,
        shell=True,
        capture_output=False
    )
    return result.returncode == 0


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--demo":
        # 演示模式
        print("\n🚀 运行演示模式（使用模拟数据）")
        run_cmd(
            'python scripts/run_demo.py',
            "演示模式"
        )

    elif len(sys.argv) > 1 and sys.argv[1] == "--fetch":
        # 仅抓取
        print("\n🚀 抓取政府政策（不进行LLM解析）")
        run_cmd(
            'python scripts/fetch_and_parse.py --skip-parse',
            "政府政策抓取"
        )

    else:
        # 完整流程
        api_key = os.environ.get("GEMINI_API_KEY", "")

        if not api_key:
            print("""
⚠️  未设置 GEMINI_API_KEY

完整流程需要 Gemini API Key 来解析政策全文。

设置方法:
    Windows:  set GEMINI_API_KEY=你的密钥
    macOS/Linux:  export GEMINI_API_KEY=你的密钥

或者使用演示模式:
    python scripts/run_policy_os.py --demo

""")
            # 运行抓取（不含LLM）
            run_cmd(
                'python scripts/fetch_and_parse.py --skip-parse',
                "政府政策抓取（无LLM解析）"
            )
        else:
            # 有API Key，运行完整流程
            print("\n🚀 运行完整 Policy OS 管道")
            print(f"✅ 已配置 GEMINI_API_KEY")

            run_cmd(
                'python scripts/fetch_and_parse.py --limit 10',
                "政府政策抓取 + LLM解析"
            )

    # 启动本地服务器
    print(f"\n{'='*60}")
    print("政策雷达预览")
    print(f"{'='*60}")
    print("""
数据已生成！打开以下文件查看：

    file://""" + str(Path(__file__).parent.parent / "policy.html") + """

或者启动本地服务器:
    cd """ + str(Path(__file__).parent.parent) + """
    python -m http.server 8888
    # 然后访问 http://localhost:8888/policy.html
""")

if __name__ == "__main__":
    main()
