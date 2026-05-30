import os
import subprocess
from pathlib import Path
from typing import Literal

import docker
from docker.errors import DockerException, NotFound
from fastapi import Depends, FastAPI, Header, HTTPException, Query
from pydantic import BaseModel

app = FastAPI(title="8BitDeck MCP Server", version="0.1.0")

MCP_AUTH_TOKEN = os.getenv("MCP_AUTH_TOKEN", "change-me")
ALLOW_MCP_ADMIN = os.getenv("ALLOW_MCP_ADMIN", "false").lower() == "true"
ADMIN_ALLOWED_COMMANDS = {
    cmd.strip()
    for cmd in os.getenv("MCP_ADMIN_ALLOWED_COMMANDS", "").split(",")
    if cmd.strip()
}
ROM_PATH = Path(os.getenv("ROM_PATH", "/roms"))
BIOS_PATH = Path(os.getenv("BIOS_PATH", "/bios"))
LOG_PATH = Path("/logs")
RETROARCH_CONTAINER = os.getenv("RETROARCH_CONTAINER", "8bitdeck-retroarch")
ROMM_CONTAINER = os.getenv("ROMM_CONTAINER", "8bitdeck-romm")


class StartSessionInput(BaseModel):
    platform: str
    rom: str
    core: str = ""
    mode: Literal["shared-screen", "browser"] = "shared-screen"


class AdminCommand(BaseModel):
    command: list[str]


def _docker_client() -> docker.DockerClient:
    try:
        return docker.from_env()
    except DockerException as exc:
        raise HTTPException(status_code=503, detail=f"Docker unavailable: {exc}") from exc


def _auth(authorization: str | None = Header(default=None)) -> None:
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    expected = f"Token {MCP_AUTH_TOKEN}"
    if authorization != expected:
        raise HTTPException(status_code=401, detail="Invalid token")


def _safe_join(base: Path, relative: str) -> Path:
    candidate = (base / relative).resolve()
    if not candidate.is_relative_to(base.resolve()):
        raise HTTPException(status_code=400, detail="Path traversal denied")
    return candidate


@app.get("/health", dependencies=[Depends(_auth)])
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/platforms", dependencies=[Depends(_auth)])
def platforms() -> dict[str, list[str]]:
    if not ROM_PATH.exists():
        return {"platforms": []}
    items = [p.name for p in ROM_PATH.iterdir() if p.is_dir()]
    return {"platforms": sorted(items)}


@app.get("/roms", dependencies=[Depends(_auth)])
def roms(platform: str | None = Query(default=None)) -> dict[str, list[str]]:
    base = ROM_PATH if platform is None else _safe_join(ROM_PATH, platform)
    if not base.exists():
        return {"roms": []}
    files = [p.relative_to(ROM_PATH).as_posix() for p in base.rglob("*") if p.is_file()]
    return {"roms": sorted(files)}


@app.get("/roms/search", dependencies=[Depends(_auth)])
def search_roms(q: str = Query(min_length=1)) -> dict[str, list[str]]:
    ql = q.lower()
    if not ROM_PATH.exists():
        return {"results": []}
    matches = [
        p.relative_to(ROM_PATH).as_posix()
        for p in ROM_PATH.rglob("*")
        if p.is_file() and ql in p.name.lower()
    ]
    return {"results": sorted(matches)[:200]}


@app.get("/session/status", dependencies=[Depends(_auth)])
def session_status() -> dict[str, str]:
    client = _docker_client()
    try:
        container = client.containers.get(RETROARCH_CONTAINER)
        return {"container": RETROARCH_CONTAINER, "status": container.status}
    except NotFound:
        return {"container": RETROARCH_CONTAINER, "status": "not-found"}


@app.post("/session/start", dependencies=[Depends(_auth)])
def session_start(payload: StartSessionInput) -> dict[str, str]:
    rom_path = _safe_join(ROM_PATH, payload.rom)
    if not rom_path.exists():
        raise HTTPException(status_code=404, detail="ROM not found")

    client = _docker_client()
    try:
        container = client.containers.get(RETROARCH_CONTAINER)
    except NotFound as exc:
        raise HTTPException(status_code=404, detail="RetroArch container not found") from exc

    launch = ["retroarch", "-L", payload.core, str(rom_path)] if payload.core else ["retroarch", str(rom_path)]
    container.exec_run(launch, detach=True)

    return {
        "status": "started",
        "platform": payload.platform,
        "rom": payload.rom,
        "mode": payload.mode,
    }


@app.post("/session/stop", dependencies=[Depends(_auth)])
def session_stop() -> dict[str, str]:
    client = _docker_client()
    try:
        container = client.containers.get(RETROARCH_CONTAINER)
    except NotFound as exc:
        raise HTTPException(status_code=404, detail="RetroArch container not found") from exc

    container.exec_run(["pkill", "-f", "retroarch"])
    return {"status": "stopped"}


@app.post("/romm/rescan", dependencies=[Depends(_auth)])
def romm_rescan() -> dict[str, str]:
    client = _docker_client()
    try:
        container = client.containers.get(ROMM_CONTAINER)
    except NotFound as exc:
        raise HTTPException(status_code=404, detail="RomM container not found") from exc

    container.restart()
    return {"status": "rescan-triggered", "container": ROMM_CONTAINER}


@app.get("/bios/check", dependencies=[Depends(_auth)])
def bios_check() -> dict[str, list[str]]:
    expected = [
        "scph1001.bin",
        "scph5501.bin",
        "Mupen64plus.rom",
        "neogeo.zip",
    ]
    missing = [name for name in expected if not (BIOS_PATH / name).exists()]
    return {"missing": missing}


@app.get("/metadata/status", dependencies=[Depends(_auth)])
def metadata_status() -> dict[str, str]:
    return {"status": "Use RomM UI for scrape progress details"}


@app.get("/logs", dependencies=[Depends(_auth)])
def logs(service: str = Query(pattern="^[a-zA-Z0-9_-]+$"), lines: int = Query(default=200, ge=1, le=2000)) -> dict[str, str]:
    log_file = _safe_join(LOG_PATH, f"{service}.log")
    if not log_file.exists() or not log_file.is_file():
        raise HTTPException(status_code=404, detail="Log file not found")

    with log_file.open("r", encoding="utf-8", errors="replace") as handle:
        tail = handle.readlines()[-lines:]
    return {"service": service, "log": "".join(tail)}


@app.post("/admin/exec", dependencies=[Depends(_auth)])
def admin_exec(payload: AdminCommand) -> dict[str, str]:
    if not ALLOW_MCP_ADMIN:
        raise HTTPException(status_code=403, detail="Admin mode disabled")
    if not payload.command:
        raise HTTPException(status_code=400, detail="No command provided")
    if payload.command[0] not in ADMIN_ALLOWED_COMMANDS:
        raise HTTPException(status_code=403, detail="Command not allowed")
    result = subprocess.run(payload.command, capture_output=True, text=True, check=False)
    return {
        "stdout": result.stdout,
        "stderr": result.stderr,
        "returncode": str(result.returncode),
    }
