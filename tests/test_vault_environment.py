"""验证所有宿主的 Vault 解析使用相同优先级。"""

import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("vault_common", ROOT / "Hook/project_memory_common.py")
common = importlib.util.module_from_spec(spec)
spec.loader.exec_module(common)


class VaultEnvironmentTests(unittest.TestCase):
    def test_shared_variable_then_project_config_for_all_hosts(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / ".git").mkdir()
            config = f"## 知识体系\n- 启用：是\n- 项目名称：测试\n- Vault根目录：{root / 'configured'}\n"
            for name in ("AGENTS.md", "CLAUDE.md"):
                (root / name).write_text(config, encoding="utf-8")
            old_env = {name: str(root / "obsolete") for name in ("CODEX_MEMORY_VAULT", "CLAUDE_MEMORY_VAULT", "PI_MEMORY_VAULT")}
            for host in ("codex", "claude", "pi"):
                for shared in ("", str(root / "shared")):
                    with self.subTest(host=host, shared=shared), patch.dict(os.environ, {**old_env, "PROJECT_MEMORY_VAULT": shared}):
                        result = common.resolve({"cwd": str(root)}, host)
                        expected = Path(shared) if shared else root / "configured"
                        self.assertEqual(result["knowledge_root"], expected / "测试/知识库")


if __name__ == "__main__":
    unittest.main()
