#!/usr/bin/env python3
"""
Elyvium Deploy UI (FastAPI + HTML)

- Runs a simple web UI to deploy Backend (always) and optionally Frontend per environment.
- Prints VERY visible logs in the terminal for every command + shows the same logs in the browser.

Run:
  python3 deploy_ui.py

Optional overrides:
  DEPLOY_UI_PORT=8090 python3 deploy_ui.py
  DEPLOY_UI_RELOAD=1 python3 deploy_ui.py
"""

import os
import shlex
import subprocess
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional, Dict, Any

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

app = FastAPI(title="Elyvium Deploy UI")

# -----------------------------------------------------------------------------
# Security guardrails
# -----------------------------------------------------------------------------
# Only allow deployment from these base directories.
ALLOWED_ROOTS = [
    "/home/elyvium/projects/ecosystem/",
]

# -----------------------------------------------------------------------------
# Environment allowlist
# -----------------------------------------------------------------------------
@dataclass(frozen=True)
class EnvConfig:
    key: str
    name: str
    default_work_front_dir: str
    default_work_back_dir: str
    default_branch: str
    front_deploy_script: Optional[str]
    backend_compose_command: str


ENVS: List[EnvConfig] = [
    EnvConfig(
        key="TEST",
        name="TEST",
        default_work_front_dir="/home/elyvium/projects/ecosystem/elyvium-ecosystem-frontend",
        default_work_back_dir="/home/elyvium/projects/ecosystem/elyvium-ecosystem",
        default_branch="sprint/23",
        front_deploy_script="./deploy.sh",
        backend_compose_command="docker compose -p elyvium-test --env-file .env.test up --build -d",
    ),
    EnvConfig(
        key="DEV",
        name="DEV",
        default_work_front_dir="/home/elyvium/projects/ecosystem/elyvium-ecosystem-frontend",
        default_work_back_dir="/home/elyvium/projects/ecosystem/elyvium-ecosystem",
        default_branch="sprint/23",
        front_deploy_script=None,  # DEV has no frontend deploy
        backend_compose_command="docker compose --env-file .env.dev up --build -d",
    ),
]

ENVS_BY_KEY: Dict[str, EnvConfig] = {e.key: e for e in ENVS}


# -----------------------------------------------------------------------------
# API models
# -----------------------------------------------------------------------------
class DeployRequest(BaseModel):
    env_key: str = Field(..., description="TEST / DEV ...")
    work_front_dir: str
    work_back_dir: str
    branch: str


# -----------------------------------------------------------------------------
# Visible logging helpers
# -----------------------------------------------------------------------------
def _ts() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _banner(title: str) -> str:
    line = "█" * 100
    return f"\n{line}\n█ {_ts()} | {title}\n{line}\n"


def _cmd_block(cmd: List[str], cwd: str) -> str:
    return (
        f"\n"
        f"┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓\n"
        f"┃ COMMAND                                                                                    ┃\n"
        f"┣━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┫\n"
        f"┃ CWD : {cwd}\n"
        f"┃ CMD : {' '.join(cmd)}\n"
        f"┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛\n"
    )


# -----------------------------------------------------------------------------
# Validation helpers
# -----------------------------------------------------------------------------
def _is_under_allowed_roots(path: str) -> bool:
    path = os.path.abspath(path)
    return any(path.startswith(root) for root in ALLOWED_ROOTS)


def _assert_git_repo(path: str) -> None:
    if not os.path.isdir(path):
        raise HTTPException(status_code=400, detail=f"Directory not found: {path}")
    if not os.path.isdir(os.path.join(path, ".git")):
        raise HTTPException(status_code=400, detail=f"Not a git repo (.git not found): {path}")


def _assert_file_exists(path: str) -> None:
    if not os.path.isfile(path):
        raise HTTPException(status_code=400, detail=f"File not found: {path}")


# -----------------------------------------------------------------------------
# Command runner (prints to terminal + returns output to UI)
# -----------------------------------------------------------------------------
def _run_cmd_capture(cmd: List[str], cwd: str) -> str:
    """
    Runs a command, prints it in a very visible format, and returns combined output.
    Raises HTTPException if the command fails.
    """
    # Terminal: very visible command block
    print(_cmd_block(cmd, cwd))

    p = subprocess.run(
        cmd,
        cwd=cwd,
        text=True,
        capture_output=True,
    )

    out = (p.stdout or "") + (p.stderr or "")

    # Terminal: show output in a visible box
    if out.strip():
        print("┌──────────────────────────── OUTPUT ────────────────────────────┐")
        print(out.rstrip())
        print("└───────────────────────────────────────────────────────────────┘")

    if p.returncode != 0:
        raise HTTPException(
            status_code=500,
            detail=(
                f"{_banner('COMMAND FAILED ❌')}"
                f"{_cmd_block(cmd, cwd)}"
                f"Exit Code: {p.returncode}\n\n"
                f"{out}"
            ),
        )

    return out


# -----------------------------------------------------------------------------
# Deploy steps
# -----------------------------------------------------------------------------
def _deploy_frontend(env: EnvConfig, work_front_dir: str, branch: str) -> str:
    log = _banner(f"FRONTEND DEPLOY | {env.name}")

    if not env.front_deploy_script:
        log += "[Frontend] Skipped (not configured for this environment)\n"
        return log

    _assert_git_repo(work_front_dir)

    script_path = os.path.join(work_front_dir, env.front_deploy_script)
    _assert_file_exists(script_path)

    log += f"Frontend Directory : {work_front_dir}\n"
    log += f"Deploy Script      : {script_path}\n"
    log += f"Branch             : {branch}\n"

    cmd = ["bash", script_path, branch]
    log += _cmd_block(cmd, work_front_dir)
    log += _run_cmd_capture(cmd, cwd=work_front_dir)

    log += "\n[Frontend] Done ✅\n"
    return log


def _deploy_backend(env: EnvConfig, work_back_dir: str, branch: str) -> str:
    log = _banner(f"BACKEND DEPLOY | {env.name}")

    _assert_git_repo(work_back_dir)

    log += f"Backend Directory  : {work_back_dir}\n"
    log += f"Branch             : {branch}\n"
    log += f"Docker Compose     : {env.backend_compose_command}\n"

    cmd1 = ["git", "fetch", "origin"]
    log += _cmd_block(cmd1, work_back_dir)
    log += _run_cmd_capture(cmd1, cwd=work_back_dir)

    cmd2 = ["git", "pull", "origin", branch]
    log += _cmd_block(cmd2, work_back_dir)
    log += _run_cmd_capture(cmd2, cwd=work_back_dir)

    compose_args = shlex.split(env.backend_compose_command)
    log += _cmd_block(compose_args, work_back_dir)
    log += _run_cmd_capture(compose_args, cwd=work_back_dir)

    log += "\n[Backend] Done ✅\n"
    return log


# -----------------------------------------------------------------------------
# API endpoints
# -----------------------------------------------------------------------------
@app.get("/api/envs")
def list_envs() -> List[Dict[str, Any]]:
    return [
        {
            "env_key": e.key,
            "name": e.name,
            "default_work_front_dir": e.default_work_front_dir,
            "default_work_back_dir": e.default_work_back_dir,
            "default_branch": e.default_branch,
            "has_frontend": bool(e.front_deploy_script),
        }
        for e in ENVS
    ]


@app.post("/api/deploy")
def deploy(req: DeployRequest) -> Dict[str, Any]:
    env = ENVS_BY_KEY.get(req.env_key)
    if not env:
        raise HTTPException(status_code=400, detail="Invalid env_key (not in allowlist).")

    # Guardrails: prevent pointing to arbitrary system paths
    for p in [req.work_front_dir, req.work_back_dir]:
        if not _is_under_allowed_roots(p):
            raise HTTPException(
                status_code=400,
                detail=f"Path not allowed: {p}\nAllowed roots: {ALLOWED_ROOTS}",
            )

    # Terminal big banner
    print(_banner(f"DEPLOY STARTED | {env.name}"))
    print(f"work_front_dir: {req.work_front_dir}")
    print(f"work_back_dir : {req.work_back_dir}")
    print(f"branch        : {req.branch}")

    log = ""
    log += _banner(f"DEPLOY STARTED | {env.name}")
    log += f"work_front_dir: {req.work_front_dir}\n"
    log += f"work_back_dir : {req.work_back_dir}\n"
    log += f"branch        : {req.branch}\n"

    log += _deploy_frontend(env, req.work_front_dir, req.branch)
    log += _deploy_backend(env, req.work_back_dir, req.branch)

    log += _banner(f"DEPLOY FINISHED ✅ | {env.name}")
    print(_banner(f"DEPLOY FINISHED ✅ | {env.name}"))

    return {"ok": True, "env": env.name, "output": log}


@app.get("/", response_class=HTMLResponse)
def ui() -> str:
    return """
<!doctype html>
<html>
<head>
  <meta charset="utf-8"/>
  <title>Elyvium Deploy UI</title>
  <style>
    body { font-family: system-ui; padding: 18px; max-width: 980px; margin: 0 auto; }
    .row { display: grid; grid-template-columns: 180px 1fr; gap: 10px; margin: 10px 0; align-items: center; }
    input, select { padding: 10px; border: 1px solid #ddd; border-radius: 8px; width: 100%; }
    button { padding: 10px 14px; border: 0; border-radius: 10px; cursor: pointer; }
    button.primary { background: #111; color: #fff; }
    .hint { color: #666; font-size: 13px; margin-top: 4px; }
    pre { background: #0b0b0b; color: #d7ffd7; padding: 14px; border-radius: 12px; overflow: auto; min-height: 240px; }
    .badge { display: inline-block; padding: 3px 8px; border-radius: 999px; background: #f2f2f2; font-size: 12px; margin-left: 8px; }
  </style>
</head>
<body>
  <h2>Elyvium Deploy UI</h2>
  <div class="hint">Select an environment, adjust inputs if needed, then deploy.</div>

  <div class="row">
    <label>Environment</label>
    <div>
      <select id="env"></select>
      <div class="hint" id="envHint"></div>
    </div>
  </div>

  <div class="row">
    <label>work_front_dir</label>
    <input id="workFront" />
  </div>

  <div class="row">
    <label>work_back_dir</label>
    <input id="workBack" />
  </div>

  <div class="row">
    <label>branch</label>
    <input id="branch" />
  </div>

  <div style="margin: 14px 0;">
    <button class="primary" onclick="deploy()">Deploy</button>
  </div>

  <h3>Output</h3>
  <pre id="out">Ready…</pre>

  <script>
    let envs = [];

    async function loadEnvs() {
      const res = await fetch('/api/envs');
      envs = await res.json();

      const sel = document.getElementById('env');
      sel.innerHTML = envs.map(e => `<option value="${e.env_key}">${e.name}</option>`).join('');
      sel.addEventListener('change', onEnvChange);

      onEnvChange();
    }

    function onEnvChange() {
      const key = document.getElementById('env').value;
      const env = envs.find(e => e.env_key === key);
      if (!env) return;

      document.getElementById('workFront').value = env.default_work_front_dir || '';
      document.getElementById('workBack').value = env.default_work_back_dir || '';
      document.getElementById('branch').value = env.default_branch || '';

      const hint = document.getElementById('envHint');
      hint.innerHTML = env.has_frontend
        ? `Frontend deploy: <span class="badge">enabled</span>`
        : `Frontend deploy: <span class="badge">skipped</span>`;
    }

    async function deploy() {
      const out = document.getElementById('out');
      out.textContent = 'Deploying...';

      const payload = {
        env_key: document.getElementById('env').value,
        work_front_dir: document.getElementById('workFront').value.trim(),
        work_back_dir: document.getElementById('workBack').value.trim(),
        branch: document.getElementById('branch').value.trim(),
      };

      try {
        const res = await fetch('/api/deploy', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });

        const data = await res.json();

        if (!res.ok) {
          out.textContent = (data && data.detail) ? data.detail : 'Deploy failed';
          return;
        }

        out.textContent = data.output || 'Done';
      } catch (e) {
        out.textContent = 'Network/Server error: ' + e;
      }
    }

    loadEnvs();
  </script>
</body>
</html>
    """.strip()


# -----------------------------------------------------------------------------
# Run server directly (no need to type uvicorn command)
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    HOST = os.getenv("DEPLOY_UI_HOST", "0.0.0.0")
    PORT = int(os.getenv("DEPLOY_UI_PORT", "7070"))
    RELOAD = os.getenv("DEPLOY_UI_RELOAD", "0") == "1"

    print(_banner("ELYVIUM DEPLOY UI SERVER"))
    print(f"Listening on: http://{HOST}:{PORT}")
    print(f"Reload mode : {'ON' if RELOAD else 'OFF'}")
    print(f"Allowed roots: {ALLOWED_ROOTS}")

    if RELOAD:
        # Reload requires an import string "module:app"
        module_name = os.path.splitext(os.path.basename(__file__))[0]
        uvicorn.run(f"{module_name}:app", host=HOST, port=PORT, reload=True)
    else:
        uvicorn.run(app, host=HOST, port=PORT)

