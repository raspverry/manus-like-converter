# tools/deploy_tools.py
"""
デプロイに関するツール。
本番環境では実際にポート公開と一時的なデプロイが可能。
"""
from core.logging_config import logger
import os
import socket
import subprocess
import time
from pathlib import Path
from typing import Optional
from tools.tool_registry import tool

# 設定情報
NGROK_ENABLED = os.getenv("ENABLE_NGROK", "false").lower() == "true"
CLOUDFLARED_ENABLED = os.getenv("ENABLE_CLOUDFLARED", "false").lower() == "true"
ALLOWED_PORTS = [int(p) for p in os.getenv("ALLOWED_PORTS", "3000,5000,8000,8080").split(",")]

@tool(
    name="deploy_expose_port",
    description="ローカルポートを一時公開する",
    parameters={
        "type": "object",
        "properties": {
            "port": {"type": "integer", "description": "公開するローカルポート"},
            "protocol": {"type": "string", "enum": ["http", "https", "tcp"], "description": "プロトコル（デフォルトはhttp）"}
        },
        "required": ["port"]
    }
)
def deploy_expose_port(port: int, protocol: str = "http"):
    """
    ローカルポートをインターネットに一時的に公開します。
    
    Args:
        port: 公開するローカルポート
        protocol: 使用するプロトコル（http, https, tcp）
        
    Returns:
        公開URLを含む文字列
    """
    # ポート範囲確認
    if port < 1 or port > 65535:
        return f"エラー: 無効なポート番号 {port}。1から65535の間で指定してください。"
    
    # 許可ポート確認
    if port not in ALLOWED_PORTS:
        return f"エラー: ポート {port} は許可されていません。許可ポート: {ALLOWED_PORTS}"
    
    # ポートの起動確認
    if not _is_port_in_use(port):
        return f"エラー: ポート {port} でサービスが起動していません。先にサービスを起動してください。"
    
    # NGROKを使用した公開
    if NGROK_ENABLED:
        return _expose_with_ngrok(port, protocol)
    
    # Cloudflaredを使用した公開
    if CLOUDFLARED_ENABLED:
        return _expose_with_cloudflared(port, protocol)
    
    # どちらも無効な場合はデモ表示
    return f"ポート {port} を https://temp-{port}-xxxxx.example.com で公開しました（デモ表示）"

def _is_port_in_use(port: int) -> bool:
    """指定ポートが使用中かどうかを確認する"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('localhost', port)) == 0

def _expose_with_ngrok(port: int, protocol: str) -> str:
    """NGROKを使用してポートを公開する"""
    try:
        # ngrokのインストール確認
        result = subprocess.run(["ngrok", "version"], capture_output=True, text=True)
        if result.returncode != 0:
            return "エラー: ngrokがインストールされていません。"
        
        # 既存のngrokプロセスをチェック
        result = subprocess.run(["pgrep", "-f", f"ngrok.*{port}"], capture_output=True, text=True)
        if result.stdout.strip():
            # 既に実行中の場合はステータスを確認
            try:
                import requests
                response = requests.get("http://localhost:4040/api/tunnels")
                data = response.json()
                for tunnel in data.get("tunnels", []):
                    if str(port) in tunnel.get("config", {}).get("addr", ""):
                        return f"ポート {port} は既に {tunnel['public_url']} で公開されています。"
            except:
                pass
        
        # 新しいngrokプロセスを起動
        cmd = ["ngrok", protocol, str(port)]
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        
        # URLの取得を待機
        time.sleep(2)
        
        # ngrok APIからURL取得
        import requests
        response = requests.get("http://localhost:4040/api/tunnels")
        data = response.json()
        
        if "tunnels" in data and data["tunnels"]:
            tunnel = data["tunnels"][0]
            public_url = tunnel["public_url"]
            return f"ポート {port} を {public_url} で公開しました。\n\n※この接続は一時的なものです。セッション終了時または最大8時間で終了します。"
        else:
            return f"エラー: ngrokトンネルの作成に失敗しました。"
    
    except Exception as e:
        logger.error(f"ngrokエラー: {str(e)}")
        return f"ngrokによるポート公開中にエラーが発生しました: {str(e)}"

def _expose_with_cloudflared(port: int, protocol: str) -> str:
    """Cloudflaredを使用してポートを公開する"""
    try:
        # cloudflaredのインストール確認
        result = subprocess.run(["cloudflared", "version"], capture_output=True, text=True)
        if result.returncode != 0:
            return "エラー: cloudflaredがインストールされていません。"
        
        # 一時ファイルにURLを書き出す
        url_file = Path.home() / f".cloudflared_url_{port}.txt"
        if url_file.exists():
            url_file.unlink()
        
        # cloudflaredプロセスを起動
        cmd = ["cloudflared", "tunnel", "--url", f"{protocol}://localhost:{port}", "--metrics", "localhost:9090"]
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        
        # URLの取得を待機
        time.sleep(3)
        
        # 標準エラー出力からURLを取得
        line = process.stderr.readline().decode('utf-8')
        while line:
            if "https://" in line:
                import re
                match = re.search(r'(https://[^\s]+)', line)
                if match:
                    url = match.group(1)
                    return f"ポート {port} を {url} で公開しました。\n\n※この接続は一時的なものです。セッション終了時または最大8時間で終了します。"
            line = process.stderr.readline().decode('utf-8')
            if not line and not url_file.exists():
                break
        
        # ファイルからURLを読み込む
        if url_file.exists():
            url = url_file.read_text().strip()
            if url:
                return f"ポート {port} を {url} で公開しました。\n\n※この接続は一時的なものです。セッション終了時または最大8時間で終了します。"
        
        return f"エラー: cloudflaredでURLの取得に失敗しました。"
    
    except Exception as e:
        logger.error(f"cloudflaredエラー: {str(e)}")
        return f"cloudflaredによるポート公開中にエラーが発生しました: {str(e)}"

@tool(
    name="deploy_apply_deployment",
    description="静的またはNext.jsのプロジェクトを本番にデプロイ",
    parameters={
        "type": "object",
        "properties": {
            "type": {"type": "string", "enum": ["static", "nextjs", "nodejs"], "description": "デプロイするプロジェクトタイプ"},
            "local_dir": {"type": "string", "description": "デプロイするディレクトリのパス"},
            "project_name": {"type": "string", "description": "プロジェクト名（任意）"}
        },
        "required": ["type", "local_dir"]
    }
)
def deploy_apply_deployment(type: str, local_dir: str, project_name: Optional[str] = None):
    """
    指定されたプロジェクトを本番環境にデプロイします。
    
    Args:
        type: プロジェクトタイプ（static, nextjs, nodejs）
        local_dir: デプロイするディレクトリのパス
        project_name: プロジェクト名（指定しない場合はディレクトリ名）
        
    Returns:
        デプロイ結果を含む文字列
    """
    # ディレクトリ存在確認
    if not os.path.exists(local_dir) or not os.path.isdir(local_dir):
        return f"エラー: ディレクトリ '{local_dir}' が存在しません。"
    
    # プロジェクト名設定
    if not project_name:
        project_name = os.path.basename(os.path.abspath(local_dir))
    
    # 環境変数
    vercel_token = os.getenv("VERCEL_TOKEN", "")
    netlify_token = os.getenv("NETLIFY_TOKEN", "")
    
    # Vercelにデプロイ
    if vercel_token:
        return _deploy_to_vercel(type, local_dir, project_name, vercel_token)
    
    # Netlifyにデプロイ
    if netlify_token:
        return _deploy_to_netlify(type, local_dir, project_name, netlify_token)
    
    # どちらも設定がない場合はデモ表示
    return f"{type}アプリを {local_dir} からデプロイしました（デモ表示）\nURL: https://{project_name}-demo.example.com"

def _deploy_to_vercel(type: str, local_dir: str, project_name: str, token: str) -> str:
    """Vercelにデプロイする"""
    try:
        # Vercel CLIがインストールされているか確認
        result = subprocess.run(["vercel", "--version"], capture_output=True, text=True)
        if result.returncode != 0:
            return "エラー: Vercel CLIがインストールされていません。"
        
        # vercel.jsonの確認
        vercel_config = os.path.join(local_dir, "vercel.json")
        if not os.path.exists(vercel_config):
            # 基本設定を作成
            import json
            config = {
                "name": project_name,
                "version": 2,
                "builds": []
            }
            
            if type == "static":
                config["builds"].append({"src": "**/*", "use": "@vercel/static"})
            elif type == "nextjs":
                config["builds"].append({"src": "package.json", "use": "@vercel/next"})
            elif type == "nodejs":
                config["builds"].append({"src": "*.js", "use": "@vercel/node"})
            
            with open(vercel_config, "w") as f:
                json.dump(config, f, indent=2)
        
        # Vercelにデプロイ
        cmd = [
            "vercel", 
            "--token", token,
            "--confirm",
            "--prod",
            "--name", project_name
        ]
        
        result = subprocess.run(cmd, cwd=local_dir, capture_output=True, text=True)
        
        if result.returncode != 0:
            logger.error(f"Vercelデプロイエラー: {result.stderr}")
            return f"Vercelへのデプロイ中にエラーが発生しました: {result.stderr}"
        
        # デプロイURLを取得
        for line in result.stdout.splitlines():
            if "https://" in line:
                return f"{type}アプリを Vercel にデプロイしました！\nURL: {line.strip()}"
        
        return f"{type}アプリを Vercel にデプロイしましたが、URLを取得できませんでした。Vercelダッシュボードを確認してください。"
    
    except Exception as e:
        logger.error(f"Vercelデプロイエラー: {str(e)}")
        return f"Vercelへのデプロイ中にエラーが発生しました: {str(e)}"

def _deploy_to_netlify(type: str, local_dir: str, project_name: str, token: str) -> str:
    """Netlifyにデプロイする"""
    try:
        # Netlify CLIがインストールされているか確認
        result = subprocess.run(["netlify", "--version"], capture_output=True, text=True)
        if result.returncode != 0:
            return "エラー: Netlify CLIがインストールされていません。"
        
        # netlify.tomlの確認
        netlify_config = os.path.join(local_dir, "netlify.toml")
        if not os.path.exists(netlify_config):
            # 基本設定を作成
            with open(netlify_config, "w") as f:
                f.write(f"[build]\n")
                
                if type == "static":
                    f.write(f"  publish = \".\"\n")
                elif type == "nextjs":
                    f.write(f"  command = \"npm run build\"\n")
                    f.write(f"  publish = \"out\"\n")
                elif type == "nodejs":
                    f.write(f"  command = \"npm run build\"\n")
                    f.write(f"  publish = \"public\"\n")
        
        # Netlifyにデプロイ
        cmd = [
            "netlify", "deploy",
            "--auth", token,
            "--dir", local_dir,
            "--prod",
            "--site-name", project_name
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode != 0:
            logger.error(f"Netlifyデプロイエラー: {result.stderr}")
            return f"Netlifyへのデプロイ中にエラーが発生しました: {result.stderr}"
        
        # デプロイURLを取得
        for line in result.stdout.splitlines():
            if "https://" in line and "Live URL" in line:
                url = line.split(":")[-1].strip()
                return f"{type}アプリを Netlify にデプロイしました！\nURL: {url}"
        
        return f"{type}アプリを Netlify にデプロイしましたが、URLを取得できませんでした。Netlifyダッシュボードを確認してください。"
    
    except Exception as e:
        logger.error(f"Netlifyデプロイエラー: {str(e)}")
        return f"Netlifyへのデプロイ中にエラーが発生しました: {str(e)}"
