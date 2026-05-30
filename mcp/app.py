import os
from pathlib import Path
from typing import Literal

import docker
from docker.errors import DockerException, NotFound
from fastapi import Depends, FastAPI, Header, HTTPException, Query
from pydantic import BaseModel

app = FastAPI(title="UnraidDeck MCP Server", version="0.1.0")

MCP_AUTH_TOKEN = os.getenv("MCP_AUTH_TOKEN", "change-me")
ALLOW_MCP_ADMIN = os.getenv("ALLOW_MCP_ADMIN", "false").lower() == "true"
ADMIN_ALLOWED_COMMANDS = {
    cmd.strip()
    for cmd in os.getenv("MCP_ADMIN_ALLOWED_COMMANDS", "").split(",")
    if cmd.strip()
}
ROM_PATH = Path(os.getenv("ROM_PATH", "/roms"))
BIOS_PATH = Path(os.getenv("BIOS_PATH", "/bios"))
RETROARCH_CONTAINER = os.getenv("RETROARCH_CONTAINER", "unraiddeck-retroarch")
ROMM_CONTAINER = os.getenv("ROMM_CONTAINER", "unraiddeck-romm")
SUNSHINE_CONTAINER = os.getenv("SUNSHINE_CONTAINER", "unraiddeck-sunshine")


class StartSessionInput(BaseModel):
    platform: str
    rom: str
    core: str = ""
    mode: Literal["shared-screen", "browser"] = "shared-screen"


class AdminCommand(BaseModel):
    action: Literal["restart-retroarch", "restart-romm", "restart-sunshine"]


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


def _rom_index() -> dict[str, Path]:
    if not ROM_PATH.exists():
        return {}
    return {p.relative_to(ROM_PATH).as_posix(): p for p in ROM_PATH.rglob("*") if p.is_file()}


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
    files = sorted(_rom_index())
    if platform is None:
        return {"roms": files}
    files = [path for path in files if path.split("/", 1)[0] == platform]
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
    rom_path = _rom_index().get(payload.rom)
    if rom_path is None:
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
    service_map = {
        "retroarch": RETROARCH_CONTAINER,
        "romm": ROMM_CONTAINER,
        "sunshine": SUNSHINE_CONTAINER,
        "mcp": "unraiddeck-mcp",
    }
    container_name = service_map.get(service)
    if not container_name:
        raise HTTPException(status_code=404, detail="Service not allowed")

    client = _docker_client()
    try:
        container = client.containers.get(container_name)
    except NotFound as exc:
        raise HTTPException(status_code=404, detail="Container not found") from exc

    raw_logs = container.logs(tail=lines)
    return {"service": service, "log": raw_logs.decode("utf-8", errors="replace")}


@app.post("/admin/exec", dependencies=[Depends(_auth)])
def admin_exec(payload: AdminCommand) -> dict[str, str]:
    if not ALLOW_MCP_ADMIN:
        raise HTTPException(status_code=403, detail="Admin mode disabled")
    if payload.action not in ADMIN_ALLOWED_COMMANDS:
        raise HTTPException(status_code=403, detail="Action not allowed")

    action_map = {
        "restart-retroarch": RETROARCH_CONTAINER,
        "restart-romm": ROMM_CONTAINER,
        "restart-sunshine": SUNSHINE_CONTAINER,
    }
    target = action_map[payload.action]
    client = _docker_client()
    try:
        client.containers.get(target).restart()
    except NotFound as exc:
        raise HTTPException(status_code=404, detail="Container not found") from exc
    return {"status": "ok", "action": payload.action, "target": target}
