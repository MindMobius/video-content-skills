from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_dsh_bundle_manifest_matches_python_package() -> None:
    package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")

    assert package["name"] == "video-subtitle-skill"
    assert package["version"] == "0.6.0"
    assert 'version = "0.6.0"' in pyproject
    assert package["dsh"]["bundle"]["patch"] == "./dsh/cordis.patch.yml"
    assert package["exports"]["./dsh"] == "./dsh/plugin.js"
    assert package["keywords"][0] == "dsh-plugin"
    assert "AGENTS.md" in package["files"]
    assert "npm-shrinkwrap.json" in package["files"]


def test_dsh_bundle_composes_skills_and_official_mcp_client() -> None:
    patch = (ROOT / "dsh" / "cordis.patch.yml").read_text(encoding="utf-8")

    assert "video-subtitle-skill/dsh" in patch
    assert "@deepseek-ai/dsh-mcp-client" in patch
    assert "inject: [videoSubtitleBundle]" in patch
    assert "serverName: video_subtitle" in patch
    assert "ctx.videoSubtitleBundle.python" in patch
    assert "failOnStartupError: false" in patch


def test_dsh_host_plugin_registers_canonical_skills_and_runtime() -> None:
    script = r"""
import { pathToFileURL } from 'node:url'

const plugin = await import(pathToFileURL(process.argv[1]).href)
const skills = []
const services = {}
plugin.apply({
  skills: { register: value => skills.push(value) },
  provide: (name, value) => { services[name] = value },
})
const runtime = services.videoSubtitleBundle
console.log(JSON.stringify({
  skills: skills.map(skill => ({
    name: skill.name,
    description: skill.description,
    provider: skill.provider,
    source: skill.source,
    resourceBase: skill.resourceBase,
    hasContent: skill.content.length > 100,
  })),
  runtime: {
    root: runtime.root,
    python: runtime.python,
    ready: runtime.ready,
    env: runtime.env,
    bootstrap: runtime.bootstrap,
  },
}))
"""
    completed = subprocess.run(
        ["node", "--input-type=module", "-e", script, str(ROOT / "dsh" / "plugin.js")],
        cwd=ROOT,
        env={**os.environ, "VIDEO_SUBTITLE_DSH_PYTHON": sys.executable},
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert [skill["name"] for skill in result["skills"]] == [
        "video-subtitle",
        "video-to-content",
        "wechat-draft-handoff",
    ]
    assert all(
        skill["provider"] == "video-subtitle-skill" for skill in result["skills"]
    )
    assert all(skill["source"] == "bundled" for skill in result["skills"])
    assert all(skill["hasContent"] for skill in result["skills"])
    assert Path(result["runtime"]["root"]).resolve() == ROOT
    assert Path(result["runtime"]["python"]).resolve() == Path(sys.executable).resolve()
    assert result["runtime"]["ready"] is True
