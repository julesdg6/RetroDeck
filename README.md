# RetroDeck

RetroDeck is an Unraid-focused Docker stack for browsing, launching, streaming, and managing a server-hosted retro ROM library.

## What it includes

- **RomM** (`6502`) for library browsing, metadata, artwork, saves, and collections.
- **EmulatorJS** (`8086`) for lightweight browser play (NES/SNES/GB/GBA/Mega Drive, etc.).
- **RetroArch session container** (`6510`) for shared-screen/heavier sessions.
- **Sunshine** (`6560` web admin; host-network streaming ports) for Moonlight streaming.
- **8BitDeck MCP server** (`6581`) for safe agent automation.

## Legal notice

You must only use ROMs/BIOS files you legally own. This project does **not** ship ROMs, BIOS files, copyrighted artwork packs, or unlicensed game databases.

## Unraid folder layout

Use these host paths:

- `/mnt/user/roms` -> `/roms:ro`
- `/mnt/user/appdata/8bitdeck/romm` -> `/config/romm` / RomM config mount
- `/mnt/user/appdata/8bitdeck/emulatorjs` -> `/config/emulatorjs`
- `/mnt/user/appdata/8bitdeck/retroarch` -> `/config/retroarch`
- `/mnt/user/appdata/8bitdeck/sunshine` -> `/config/sunshine`
- `/mnt/user/appdata/8bitdeck/mcp` -> `/config/mcp`
- `/mnt/user/appdata/8bitdeck/bios` -> `/bios`
- `/mnt/user/appdata/8bitdeck/saves` -> `/saves`
- `/mnt/user/appdata/8bitdeck/states` -> `/states`

## Quick start (Unraid Docker Compose Manager)

1. Copy `.env.example` to `.env` and set `MCP_AUTH_TOKEN`.
2. In Unraid, open Docker Compose Manager and deploy this repository's `docker-compose.yml`.
3. Keep `/mnt/user/roms` mounted read-only unless you explicitly need write access.
4. Open services:
   - RomM: `http://<unraid-ip>:6502`
   - EmulatorJS: `http://<unraid-ip>:8086`
   - RetroArch web/noVNC: `http://<unraid-ip>:6510`
   - Sunshine admin: `http://<unraid-ip>:6560`
   - MCP API: `http://<unraid-ip>:6581`

## 8-bit themed default ports

- `ROMM_PORT=6502`
- `EMULATORJS_PORT=8086`
- `RETROARCH_PORT=6510`
- `SUNSHINE_PORT=6560`
- `MCP_PORT=6581`

## Security guidance

- Do **not** expose this stack directly to the public internet.
- Prefer LAN-only access, or private access through Tailscale/WireGuard/reverse proxy auth.
- MCP endpoints require an `Authorization` header using the MCP token (`Token <MCP_AUTH_TOKEN>`).
- MCP ROM browsing is restricted to mounted paths only.
- Sunshine pairing codes/PINs should never be posted publicly.

## Sunshine + Moonlight pairing

1. Start `retroarch` and `sunshine`.
2. Open Sunshine web admin on `:6560` and complete initial setup.
3. In Moonlight, add your Unraid host IP.
4. Enter the pairing PIN/code shown in Moonlight into Sunshine.
5. Launch your RetroArch app entry and join your shared-screen session.

## MCP API (safe operations)

Base URL: `http://<host>:6581`

- `GET /health`
- `GET /platforms`
- `GET /roms`
- `GET /roms/search?q=sonic`
- `GET /session/status`
- `POST /session/start`
- `POST /session/stop`
- `POST /romm/rescan`
- `GET /bios/check`
- `GET /metadata/status`
- `GET /logs?service=retroarch`

`/admin/exec` is disabled unless `ALLOW_MCP_ADMIN=true`, and command names must be explicitly allow-listed in `MCP_ADMIN_ALLOWED_COMMANDS`.

### Example MCP tool mapping

- `8bitdeck.health`
- `8bitdeck.list_platforms`
- `8bitdeck.search_roms`
- `8bitdeck.start_game`
- `8bitdeck.stop_game`
- `8bitdeck.session_status`
- `8bitdeck.rescan_library`
- `8bitdeck.check_bios`
- `8bitdeck.read_logs`

### `start_game` payload example

```json
{
  "platform": "snes",
  "rom": "Super Mario Kart.sfc",
  "core": "snes9x",
  "mode": "shared-screen"
}
```

## Add MCP endpoint to your agent

Configure your agent/tool client with:

- Endpoint: `http://<unraid-ip>:6581`
- Header: `Authorization: Token <MCP_AUTH_TOKEN>`

## Troubleshooting

- **Missing BIOS**: call `GET /bios/check`, then add missing files to `/mnt/user/appdata/8bitdeck/bios`.
- **Controller not detected**: verify USB/Bluetooth passthrough and RetroArch input driver settings.
- **Black screen in Sunshine**: confirm `/dev/dri` mapping and GPU/iGPU availability; check Sunshine logs.
- **Audio delay**: use wired network where possible, tune Moonlight bitrate/FPS/audio buffer.
- **RomM cannot scan ROMs**: verify ROM path mount and permissions; ensure share is readable by container UID/GID.
- **Permissions on appdata**: match `PUID/PGID` with Unraid file ownership.
- **GPU/iGPU passthrough**: verify `retroarch` has `/dev/dri:/dev/dri` and host supports hardware acceleration.

## Notes

- Browser play uses RomM/EmulatorJS.
- Shared-screen multiplayer starts RetroArch and streams with Sunshine/Moonlight.
- Suggested future stretch goals: RomM shared-session button, Discord invite generation, save-state sharing, per-friend controller mapping, cabinet mode, RetroAchievements, Tailscale sidecar, optional WebRTC, and Unraid XML template generation.
