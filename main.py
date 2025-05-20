# main.py
"""
Manusのようなエージェントのメイン実行ファイル。
CLI、Gradio WebUI、またはStreamlit WebUIを起動します。
"""

import os
import sys
import argparse
from core.logging_config import logger

from dotenv import load_dotenv

load_dotenv()

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

def main():
    parser = argparse.ArgumentParser(description="Manus-Like Agent")
    parser.add_argument("--task", help="初期タスクの説明")
    parser.add_argument("--ui", choices=["cli", "gradio", "streamlit"], default="gradio", 
                        help="使用するUI (cli, gradio, または streamlit, デフォルト: gradio)")
    parser.add_argument("--port", type=int, default=8501, help="WebUIのポート (デフォルト: 8501)")
    args = parser.parse_args()
    
    if args.ui == "cli":
        # CLIインターフェース起動
        from ui.cli import main as cli_main
        try:
            cli_main(initial_task=args.task)
        except KeyboardInterrupt:
            print("\nプログラムが中断されました")
            sys.exit(0)
        except Exception as e:
            logger.error(f"予期しないエラーが発生しました: {str(e)}", exc_info=True)
            sys.exit(1)
    
    elif args.ui == "gradio":
        # Gradio WebUI起動
        try:
            # Gradioをインポート (インストールされているか確認)
            try:
                import gradio
            except ImportError:
                print("Gradioがインストールされていません。インストールしてください: pip install gradio>=4.11.0")
                print("または別のUIを選択: --ui streamlit または --ui cli")
                sys.exit(1)
                
            print(f"Gradio WebUIを起動します (ポート: {args.port})...")
            
            # Gradioアプリを直接インポートして実行
            from ui.gradio_app import create_ui
            
            if args.task:
                print(f"注意: WebUIモードでは初期タスク引数 '{args.task}' は無視されます。WebUI内でタスクを設定してください。")
            
            # Gradioアプリを起動
            demo = create_ui()
            demo.queue()
            demo.launch(
                server_name="0.0.0.0", 
                server_port=args.port,
                share=False
            )
            
        except KeyboardInterrupt:
            print("\nGradio WebUIが中断されました")
            sys.exit(0)
        except Exception as e:
            logger.error(f"Gradio起動中にエラーが発生しました: {str(e)}", exc_info=True)
            print("\n代わりにCLIを使用するには: python main.py --ui cli")
            print("またはStreamlitを使用するには: python main.py --ui streamlit")
            sys.exit(1)
    
    else:  # args.ui == "streamlit"
        # Streamlit WebUI起動
        try:
            # Streamlitをインポート (インストールされているか確認)
            try:
                import streamlit
            except ImportError:
                print("Streamlitがインストールされていません。インストールしてください: pip install streamlit")
                print("または別のUIを選択: --ui gradio または --ui cli")
                sys.exit(1)
                
            # コマンドラインでStreamlitを直接呼び出す方法（より安全）
            import subprocess
            
            # 実行ファイルのパスを取得
            file_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ui", "streamlit_app.py")
            
            if args.task:
                print(f"注意: WebUIモードでは初期タスク引数 '{args.task}' は無視されます。WebUI内でタスクを設定してください。")
            
            # Streamlit起動コマンド
            print(f"Streamlit WebUIを起動します (ポート: {args.port})...")
            
            # サブプロセスで起動（bootstrap APIの代わりにこの方法を使用）
            cmd = [sys.executable, "-m", "streamlit", "run", file_path, "--server.port", str(args.port)]
            subprocess.run(cmd)
            
        except KeyboardInterrupt:
            print("\nStreamlit WebUIが中断されました")
            sys.exit(0)
        except Exception as e:
            logger.error(f"Streamlit起動中にエラーが発生しました: {str(e)}", exc_info=True)
            print("\n代わりにCLIを使用するには: python main.py --ui cli")
            print("またはGradioを使用するには: python main.py --ui gradio")
            sys.exit(1)

if __name__ == "__main__":
    main()
