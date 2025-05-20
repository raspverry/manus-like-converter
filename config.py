# config.py
"""
Perl-Python 変換エージェントシステムの設定ファイル。
環境変数からの設定読み込みと検証を強化。
"""
import os
import logging
from typing import Dict, Any, List
from dotenv import load_dotenv

# 環境変数のロード
load_dotenv()

# ログ設定
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("config")

# ヘルパー関数: 環境変数取得
def get_env(key: str, default: Any = None) -> Any:
    return os.getenv(key, default)

def get_bool(key: str, default: bool = False) -> bool:
    value = os.getenv(key)
    if value is None:
        return default
    return value.lower() in ('true', 'yes', '1', 'y', 'on')

def get_int(key: str, default: int = 0) -> int:
    value = os.getenv(key)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        logger.warning(f"環境変数 {key} を整数に変換できません: {value}")
        return default

def get_float(key: str, default: float = 0.0) -> float:
    value = os.getenv(key)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        logger.warning(f"環境変数 {key} を浮動小数点に変換できません: {value}")
        return default

def get_list(key: str, default: List = None, separator: str = ",") -> List:
    if default is None:
        default = []
    
    value = os.getenv(key)
    if value is None:
        return default
    
    return [item.strip() for item in value.split(separator) if item.strip()]

# 基本設定
BASE_CONFIG: Dict[str, Any] = {
    "system": {
        "name": get_env("AGENT_NAME", "Perl-Python Converter"),
        "version": get_env("AGENT_VERSION", "0.1.0"),
        "default_language": get_env("DEFAULT_LANGUAGE", "ja"),
        "log_level": get_env("LOG_LEVEL", "INFO"),
        "workspace_dir": os.path.abspath(get_env("WORKSPACE_DIR", "workspace")),
        "prompt_dir": os.path.abspath(get_env("PROMPT_DIR", "prompts")),
    },
    "llm": {
        "provider": "openai",  # 変更: azureからopenaiへ
        "model": get_env("LLM_MODEL", "gpt-4o"),  # デフォルトでGPT-4o
        "temperature": get_float("LLM_TEMPERATURE", 0.2),
        "max_tokens": get_int("LLM_MAX_TOKENS", 2000),
        "context_window": get_int("LLM_CONTEXT_WINDOW", 8000),
        "planning_model": get_env("LLM_PLANNING_MODEL", "gpt-4o"),
        "use_langchain": get_bool("USE_LANGCHAIN", False),  # LangChainを使用するかどうか
    },
    "agent_loop": {
        "max_iterations": get_int("AGENT_MAX_ITERATIONS", 40),
        "max_time_seconds": get_int("AGENT_MAX_TIME_SECONDS", 1800),
        "auto_summarize_threshold": get_int("AGENT_AUTO_SUMMARIZE_THRESHOLD", 30),
        "tool_timeout_seconds": get_int("AGENT_TOOL_TIMEOUT_SECONDS", 90),
    },
    "tools": {
        "message": {"enabled": True},
        "file": {"enabled": True, "allowed_dirs": ["/home/ubuntu"]},
        "shell": {
            "enabled": True, 
            "timeout_seconds": get_int("AGENT_TOOL_TIMEOUT_SECONDS", 90), 
            "max_output_chars": 15000
        },
        "browser": {
            "enabled": True,
            "timeout_seconds": get_int("AGENT_TOOL_TIMEOUT_SECONDS", 60),
            "user_agent": f"PerlPythonConverter/{get_env('AGENT_VERSION', '0.1.0')}",
            "headless": True
        },
        "info": {
            "enabled": True, 
            "search_max_results": get_int("INFO_TOOL_MAX_RESULTS", 5),
            "default_language": get_env("INFO_TOOL_DEFAULT_LANGUAGE", "ja")
        },
        "deploy": {
            "enabled": True, 
            "allowed_ports": get_list("ALLOWED_PORTS", [3000, 5000, 8000, 8080])
        },
    },
    "codeact": {
        "enabled": True,
        "timeout_seconds": get_int("CODEACT_EXECUTION_TIMEOUT", 60),
        "allowed_modules": get_list("CODEACT_ALLOWED_MODULES", 
                                 ["os", "pandas", "numpy", "matplotlib", "requests", "bs4", 
                                  "re", "json", "csv", "math", "datetime", "time"]),
        "max_iterations": 5,
        "max_code_size": get_int("CODEACT_MAX_CODE_SIZE", 50000)
    },
    "converter": {  # 新規追加: 変換者固有の設定
        "perl_parser": get_env("PERL_PARSER", "ppi"),  # 使用するPerlパーサー (ppi, perltidy等)
        "add_type_hints": get_bool("ADD_TYPE_HINTS", True),  # Pythonタイプヒントを追加するか
        "style_format": get_env("STYLE_FORMAT", "pep8"),  # Pythonコードスタイル
        "test_conversion": get_bool("TEST_CONVERSION", True),  # 変換結果をテストするか
        "preserve_comments": get_bool("PRESERVE_COMMENTS", True),  # コメントを保持するか
        "segment_size": get_int("SEGMENT_SIZE", 500),  # 変換時のコードセグメントサイズ
    },
    "memory": {
        "todo_file": "todo.md",
        "notes_file": "notes.md",
        "max_files_to_track": 200,
        "use_vector_memory": get_bool("USE_VECTOR_MEMORY", True),
    },
    "vector_memory": {
        "enabled": get_bool("USE_VECTOR_MEMORY", True),
        "embedding_model": get_env("VECTOR_EMBEDDING_MODEL", "all-MiniLM-L6-v2"),
        "collection_name": get_env("VECTOR_COLLECTION_NAME", "agent_memory"),
        "results_limit": get_int("VECTOR_RESULTS_LIMIT", 3),
    },
    "docker": {
        "enabled": get_bool("USE_DOCKER", True),
        "image_name": get_env("DOCKER_IMAGE_NAME", "perl-python-sandbox:latest"),
        "memory_limit": get_env("DOCKER_MEMORY_LIMIT", "512m"),
        "cpu_limit": get_float("DOCKER_CPU_LIMIT", 0.5),
    },
    "security": {
        "sandbox_enabled": get_bool("USE_DOCKER", True),
        "allow_sudo": get_bool("SANDBOX_ALLOW_SUDO", False),
        "allow_network": get_bool("SANDBOX_ALLOW_NETWORK", True),
        "blocked_domains": get_list("SANDBOX_BLOCKED_DOMAINS", []),
        "blocked_commands": get_list("SANDBOX_BLOCKED_COMMANDS", 
                                  ["rm -rf /", "shutdown", "reboot", "passwd"]),
    },
    "ui": {
        "chainlit_port": get_int("CHAINLIT_PORT", 8002),
        "streamlit_port": get_int("STREAMLIT_PORT", 8501),
        "gradio_port": get_int("GRADIO_PORT", 8000),
        "api_server": {
            "host": get_env("API_SERVER_HOST", "0.0.0.0"),
            "port": get_int("API_SERVER_PORT", 8001)
        }
    },
    "external_services": {
        "search": {
            "api_key": get_env("SEARCH_API_KEY", ""),
            "api_url": get_env("SEARCH_API_URL", "https://api.bing.microsoft.com/v7.0/search")
        },
        "deploy": {
            "enable_ngrok": get_bool("ENABLE_NGROK", False),
            "enable_cloudflared": get_bool("ENABLE_CLOUDFLARED", False),
            "vercel_token": get_env("VERCEL_TOKEN", ""),
            "netlify_token": get_env("NETLIFY_TOKEN", "")
        }
    }
}

def validate_openai_credentials() -> None:
    """OpenAI認証情報の検証"""
    api_key = os.getenv("OPENAI_API_KEY")
    
    if not api_key:
        logger.error("OpenAI API キーが設定されていません。LLM機能が動作しません。")
        raise EnvironmentError("OPENAI_API_KEY 環境変数が必要です。")
        
    logger.info("OpenAI API 設定を確認しました")

def override_from_env(config: Dict[str, Any]) -> Dict[str, Any]:
    """
    環境変数から設定を上書きする。
    """
    # API認証の検証
    validate_openai_credentials()
    
    # モデル名の上書き
    if os.getenv("LLM_MODEL"):
        config["llm"]["model"] = os.getenv("LLM_MODEL")
    
    # LangChain使用フラグの上書き
    if os.getenv("USE_LANGCHAIN"):
        config["llm"]["use_langchain"] = get_bool("USE_LANGCHAIN", False)
    
    # その他の設定上書き
    if os.getenv("LLM_TEMPERATURE"):
        config["llm"]["temperature"] = float(os.getenv("LLM_TEMPERATURE"))
    
    if os.getenv("LOG_LEVEL"):
        config["system"]["log_level"] = os.getenv("LOG_LEVEL")
    
    if os.getenv("WORKSPACE_DIR"):
        config["system"]["workspace_dir"] = os.path.abspath(os.getenv("WORKSPACE_DIR"))
    
    if os.getenv("USE_VECTOR_MEMORY") == "False":
        config["memory"]["use_vector_memory"] = False
        config["vector_memory"]["enabled"] = False
    
    if os.getenv("USE_DOCKER") == "False":
        config["docker"]["enabled"] = False
        config["security"]["sandbox_enabled"] = False
    
    # コンバーター設定の上書き
    if os.getenv("PERL_PARSER"):
        config["converter"]["perl_parser"] = os.getenv("PERL_PARSER")
    
    if os.getenv("ADD_TYPE_HINTS") == "False":
        config["converter"]["add_type_hints"] = False
    
    return config

# 最終設定を構築
CONFIG = override_from_env(BASE_CONFIG)
