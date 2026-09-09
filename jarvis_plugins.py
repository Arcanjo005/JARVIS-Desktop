"""JARVIS plugin manager. Plugins live in the project plugins/ directory."""
import os
import importlib.util
from pathlib import Path


class PluginManager:
    def __init__(self, logger=None, plugin_dir=None):
        self.logger = logger
        self.plugin_dir = Path(plugin_dir or os.path.join(os.getcwd(), "plugins"))
        self.plugin_dir.mkdir(parents=True, exist_ok=True)
        self.plugins = []
        self.reload()

    def reload(self):
        self.plugins = []
        for path in sorted(self.plugin_dir.glob("*.py")):
            if path.name.startswith("_"):
                continue
            try:
                spec = importlib.util.spec_from_file_location(f"jarvis_plugin_{path.stem}", path)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                if callable(getattr(module, "can_handle", None)) and callable(getattr(module, "handle", None)):
                    self.plugins.append((path.stem, module))
                    if self.logger:
                        self.logger.info(f"Plugin carregado: {path.stem}", "PLUGIN")
            except Exception as e:
                if self.logger:
                    self.logger.error(e, f"Falha ao carregar plugin {path.name}", "PLUGIN")
        return len(self.plugins)

    def try_handle(self, message, context=None):
        for name, module in list(self.plugins):
            try:
                if module.can_handle(message):
                    return module.handle(message, context or {})
            except Exception as e:
                if self.logger:
                    self.logger.error(e, f"Erro no plugin {name}", "PLUGIN")
        return None

    def list_plugins(self):
        return [name for name, _ in self.plugins]
