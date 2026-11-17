"""Tests for self-evolution dedicated model configuration and resolution."""
from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from astra_backend.evolution_config import (
    load_evolution_config,
    save_evolution_config,
    resolve_evolution_llm_runtime,
)


class EvolutionModelConfigTest(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.tmp_path = Path(self.tmp.name)
        self.cfg_file = self.tmp_path / "evolution_config.json"
        self.file_patcher = patch("astra_backend.evolution_config.EVOLUTION_CONFIG_FILE", self.cfg_file)
        self.file_patcher.start()
        self.addCleanup(self.file_patcher.stop)

    def test_default_config_fallback(self):
        cfg = load_evolution_config()
        self.assertEqual(cfg["model_id"], "auto")
        self.assertEqual(cfg["reasoning_effort"], "high")
        self.assertEqual(cfg["thinking_timeout"], 300.0)
        self.assertEqual(cfg["analysis_depth"], "deep")

    def test_save_and_reload_evolution_config(self):
        saved = save_evolution_config({
            "model_id": "glm-5.3-flash",
            "reasoning_effort": "max",
            "thinking_timeout": 450.0,
            "analysis_depth": "deep",
            "start_time": "2026-09-10 12:00:00",
        })
        self.assertEqual(saved["model_id"], "glm-5.3-flash")
        self.assertEqual(saved["reasoning_effort"], "max")
        self.assertEqual(saved["thinking_timeout"], 450.0)
        self.assertEqual(saved["start_time"], "2026-09-10 12:00:00")

        # Verify disk content
        reloaded = load_evolution_config()
        self.assertEqual(reloaded["model_id"], "glm-5.3-flash")
        self.assertEqual(reloaded["reasoning_effort"], "max")
        self.assertEqual(reloaded["thinking_timeout"], 450.0)

    def test_resolve_evolution_llm_runtime_dedicated(self):
        cfg = {
            "model_id": "glm-5.3-flash",
            "reasoning_effort": "max",
            "thinking_timeout": 350.0,
        }
        with patch("astra_backend.llm_manager.resolve_model_runtime", return_value={
            "model": "glm-5.3-flash",
            "base_url": "https://tokenrhythm.studio/v1",
            "api_key": "test-key",
            "api_format": "openai_chat",
        }):
            rt = resolve_evolution_llm_runtime(cfg)
            self.assertEqual(rt["model"], "glm-5.3-flash")
            self.assertEqual(rt["reasoning_effort"], "max")
            self.assertEqual(rt["thinking_timeout"], 350.0)
            self.assertTrue(rt["evolution_dedicated"])

    def test_resolve_evolution_llm_runtime_auto_fallback(self):
        cfg = {
            "model_id": "auto",
            "reasoning_effort": "high",
            "thinking_timeout": 300.0,
        }
        with patch("astra_backend.llm_manager.get_active_llm_runtime", return_value={
            "model": "gemini-3.8-flash",
            "base_url": "https://api.astra.example.com/v1",
            "api_key": "key",
            "api_format": "openai_chat",
        }):
            rt = resolve_evolution_llm_runtime(cfg)
            self.assertEqual(rt["model"], "gemini-3.8-flash")
            self.assertEqual(rt["reasoning_effort"], "high")
            self.assertFalse(rt["evolution_dedicated"])
