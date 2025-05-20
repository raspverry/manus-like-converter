# convert.py
#!/usr/bin/env python
"""
Perlコードを変換するコマンドラインスクリプト。
"""

import os
import sys
import argparse
import time
from pathlib import Path

from core.logging_config import logger
from core.converter_agent import create_converter_agent
from config import CONFIG

def main():
    """メイン関数"""
    parser = argparse.ArgumentParser(description="Perl から Python へのコード変換ツール")
    
    parser.add_argument("--input", "-i", required=True, help="変換するPerlファイルのパス")
    parser.add_argument("--output", "-o", help="出力するPythonファイルのパス（指定しない場合は入力ファイル名.py）")
    parser.add_argument("--detailed", "-d", action="store_true", help="詳細な変換プロセスを表示")
    parser.add_argument("--test", "-t", action="store_true", help="変換後のコードをテストして結果を表示")
    parser.add_argument("--no-test", action="store_true", help="コードテストをスキップ（--testが指定されている場合は無視）")
    parser.add_argument("--segment-size", "-s", type=int, default=0, help="コードセグメントの最大サイズ（デフォルト: 設定値）")
    parser.add_argument("--type-hints", action="store_true", help="Pythonタイプヒントを追加")
    parser.add_argument("--no-type-hints", action="store_true", help="Pythonタイプヒントを追加しない")
    parser.add_argument("--style", choices=["pep8", "google", "numpy"], default="pep8", help="出力コードのスタイル")
    
    args = parser.parse_args()
    
    # 入力ファイルの確認
    input_path = Path(args.input)
    if not input_path.exists():
        print(f"エラー: 入力ファイル '{input_path}' が存在しません。")
        return 1
    
    # 出力ファイルのパス設定
    if args.output:
        output_path = Path(args.output)
    else:
        # 入力ファイルと同じディレクトリに、拡張子を.pyに変更して出力
        output_path = input_path.with_suffix(".py")
    
    # 設定の更新
    if args.detailed:
        os.environ["LOG_LEVEL"] = "DEBUG"
    
    if args.test:
        CONFIG["converter"]["test_conversion"] = True
    elif args.no_test:
        CONFIG["converter"]["test_conversion"] = False
    
    if args.segment_size > 0:
        CONFIG["converter"]["segment_size"] = args.segment_size
    
    if args.type_hints:
        CONFIG["converter"]["add_type_hints"] = True
    elif args.no_type_hints:
        CONFIG["converter"]["add_type_hints"] = False
    
    CONFIG["converter"]["style_format"] = args.style
    
    # Perlコードの読み込み
    try:
        with open(input_path, 'r', encoding='utf-8') as f:
            perl_code = f.read()
    except Exception as e:
        print(f"エラー: ファイル '{input_path}' の読み込み中にエラーが発生しました: {e}")
        return 1
    
    # 開始時間
    start_time = time.time()
    
    # 変換の実行
    print(f"\n{'=' * 60}")
    print(f"Perl → Python 変換を開始します: {input_path}")
    print(f"{'=' * 60}")
    
    # 変換エージェントの作成
    agent = create_converter_agent()
    
    try:
        # 変換の実行
        python_code = agent.start_conversion(perl_code, str(output_path))
        
        # 結果の表示
        elapsed_time = time.time() - start_time
        print(f"\n{'=' * 60}")
        print(f"変換完了！ 処理時間: {elapsed_time:.2f}秒")
        print(f"変換結果: {output_path}")
        print(f"{'=' * 60}")
        
        if args.detailed:
            # エラーがある場合は表示
            if agent._python_issues:
                print("\n警告: 変換中に以下の問題が検出されました：")
                for i, issue in enumerate(agent._python_issues, 1):
                    print(f"{i}. {issue}")
        
        return 0
    
    except KeyboardInterrupt:
        print("\n変換が中断されました。")
        agent.stop()
        return 1
    
    except Exception as e:
        print(f"\nエラー: 変換中に予期しないエラーが発生しました: {e}")
        import traceback
        traceback.print_exc()
        return 1

if __name__ == "__main__":
    sys.exit(main())
