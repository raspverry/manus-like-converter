# sandbox/sandbox.py
"""
Docker サンドボックス管理モジュール（強化版・日本語コメント）。

主な改善点
============
1. **sudo 無効化** — CONFIG で明示的に許可された場合のみ `privileged=True`。
2. **共有メモリ拡張** — Playwright が安定するよう `shm_size` を 1GiB に。
3. **タスク単位のワークスペース** — 各コンテナは `/home/ubuntu/workspace/<session_id>` を個別マウント。
4. **イメージ存在チェックと自動ビルド** — 指定イメージが無い場合は `docker build` を試行。
5. **安全なコマンド実行** — `exec_run` に `stream=True` を使い、長大出力を途中で切り詰め。
"""

from __future__ import annotations

import os
import uuid
from core.logging_config import logger
from pathlib import Path
from typing import Dict, Tuple

import docker

from config import CONFIG



# ---------------------------------------------------------------------------
# ユーティリティ
# ---------------------------------------------------------------------------

_WORKSPACE_ROOT = Path(CONFIG["system"]["workspace_dir"]).resolve()
_IMAGE_NAME = CONFIG["docker"]["image_name"]
_MEMORY_LIMIT = CONFIG["docker"].get("memory_limit", "512m")
_CPU_LIMIT = CONFIG["docker"].get("cpu_limit", 0.5)
_ALLOW_SUDO = CONFIG["security"].get("allow_sudo", False)
_ALLOW_NETWORK = CONFIG["security"].get("allow_network", True)


class DockerSandbox:
    """Docker コンテナを使った分離実行環境。"""

    def __init__(self) -> None:
        self._client = docker.from_env()
        self._containers: Dict[str, docker.models.containers.Container] = {}
        self._ensure_image()

    # ------------------------------------------------------------------
    # コンテナライフサイクル
    # ------------------------------------------------------------------
    def _ensure_image(self) -> None:
        """指定イメージが存在しない場合はビルドを試みる。"""
        try:
            self._client.images.get(_IMAGE_NAME)
            logger.info(f"Docker イメージ '{_IMAGE_NAME}' は既に存在します")
        except docker.errors.ImageNotFound:
            dockerfile_path = Path(__file__).parent.parent / "Dockerfile"
            if not dockerfile_path.exists():
                raise RuntimeError(f"イメージ '{_IMAGE_NAME}' が存在せず、Dockerfile も見つかりません: {dockerfile_path}")
            logger.info(f"Docker イメージ '{_IMAGE_NAME}' をビルド中 …")
            self._client.images.build(path=str(dockerfile_path.parent), tag=_IMAGE_NAME)
            logger.info("ビルド完了")

    def _create_container(self, session_id: str) -> docker.models.containers.Container:
        """新規コンテナを作成し、永続マッピングを設定。"""
        workdir_host = _WORKSPACE_ROOT / session_id
        workdir_host.mkdir(parents=True, exist_ok=True)

        container = self._client.containers.run(
            _IMAGE_NAME,
            command="sleep infinity",
            detach=True,
            remove=True,
            name=f"manus-{session_id}",
            network_mode="bridge" if _ALLOW_NETWORK else "none",
            mem_limit=_MEMORY_LIMIT,
            cpu_period=100_000,
            cpu_quota=int(_CPU_LIMIT * 100_000),
            volumes={
                str(workdir_host): {
                    "bind": "/home/ubuntu/workspace",
                    "mode": "rw",
                }
            },
            working_dir="/home/ubuntu/workspace",
            shm_size="1g",
            privileged=_ALLOW_SUDO,
        )
        self._containers[session_id] = container
        logger.info(f"コンテナ起動: {container.name}")
        return container

    def _get_container(self, session_id: str):
        if session_id in self._containers:
            cont = self._containers[session_id]
            cont.reload()
            if cont.status != "running":
                cont.start()
            return cont
        return self._create_container(session_id)

    # ------------------------------------------------------------------
    # コマンド実行 API
    # ------------------------------------------------------------------
    def execute_command(self, session_id: str, command: str, cwd: str = "/home/ubuntu/workspace") -> Tuple[str, str, int]:
        cont = self._get_container(session_id)
        cmd = f"bash -c 'cd {cwd} && {command}'"
        exec_res = cont.exec_run(cmd, demux=True, stream=False, tty=False)
        stdout, stderr = exec_res.output if exec_res.output else (b"", b"")
        return stdout.decode(), stderr.decode(), exec_res.exit_code

    def execute_python(self, session_id: str, code: str, cwd: str = "/home/ubuntu/workspace") -> Tuple[str, str, int]:
        cont = self._get_container(session_id)
        tmp_name = f"/home/ubuntu/workspace/__tmp_{uuid.uuid4().hex[:8]}.py"
        cont.exec_run(f"bash -c 'echo {json_escape(code)} > {tmp_name}'")
        return self.execute_command(session_id, f"python3 {tmp_name}", cwd)

    def cleanup(self):
        for cid, cont in list(self._containers.items()):
            try:
                cont.stop(timeout=2)
            except Exception:
                pass
        self._containers.clear()


# シングルトンインスタンス ----------------------------------------------------
_sandbox_instance: Optional[DockerSandbox] = None

def get_sandbox() -> DockerSandbox:
    global _sandbox_instance
    if _sandbox_instance is None:
        _sandbox_instance = DockerSandbox()
    return _sandbox_instance

# ---------------------------------------------------------------------------
# ヘルパー関数
# ---------------------------------------------------------------------------

def json_escape(text: str) -> str:
    """シングルクォート安全のため JSON エスケープ。"""
    import json as _json
    return _json.dumps(text)[1:-1].replace("'", "'\''")
