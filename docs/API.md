# Jarvis robot HTTP API

The robot (ESP32-S3, firmware board `wall-e-xiao`) serves its settings page and a small JSON API on
**port 80, plain HTTP, no login**. It is meant for your own home network only. The landing page in this
repository and the [Android app](https://github.com/txrx007-hub/jarvis-robot-android) both use exactly
these endpoints, so anything that can speak HTTP can control the robot.

The server starts when the robot connects to WiFi and stops when WiFi drops or the robot goes into
deep sleep. Replies are `application/json` unless noted. `<ip>` is the robot's address.

| Method | Path | Purpose |
|---|---|---|
| GET | `/` | The landing page (`index.html`, embedded in the firmware) |
| GET | `/api/status` | Live device info, poll about once a second |
| GET | `/api/ping` | Empty `200` reply, for measuring round-trip time |
| GET | `/api/settings` | Every setting with its current value and limits |
| POST | `/api/settings` | Change one setting |
| POST | `/api/reset` | Reset all settings to defaults |
| POST | `/api/drive` | Drive the wheels (remote control) |
| POST | `/api/power` | Nap, wake up, deep sleep |
| POST | `/api/volume` | Set the speaker volume (the requested volume; the cap from the settings still applies) |
| POST | `/api/server` | Choose the voice server: the xiaozhi.me cloud or an own server on the LAN |
| GET | `/api/net` | What the robot has sent and received over Wi-Fi since it started: `tx_pkts`, `rx_pkts`, `tx_bytes`, `rx_bytes` (32 bit counters that wrap) and `t_ms` (its clock). Counted where lwIP meets the Wi-Fi driver, so it is every IP packet of the robot. About 100 bytes, meant to be asked a few times a second; a reader works out the rates from two readings |
| POST | `/api/stop` | Stop what Jarvis is saying or playing (a song, a radio stream) at once; the page's Stop button |
| POST | `/api/photo` | One JPEG from the camera (`?live=1` for the live view: smaller picture, nothing shown on the robot's own screen; taken in a task of its own so driving keeps working) (the page and the app hand it to the backend panel, `POST /api/dcim`, which keeps it in `dcim/` on the PC) (`503` with a text reason when there is no camera, or while napping); the page's Camera button |

## GET /api/status

```json
{
  "board": "wall-e-xiao/2.5.0", "board_name": "ESP32 S3 Sense",
  "camera_detected": true, "camera_sensor": "OV3660",
  "ssid": "HomeWiFi", "ip": "192.168.1.50", "mac": "AA:BB:CC:DD:EE:FF", "rssi": -51,
  "uptime_s": 946, "state": 3, "napping": false, "power": "battery",
  "cpu_load": 42, "cpu_mhz": 240, "fps": 27,
  "ram_free_kb": 71, "ram_total_kb": 399, "psram_free_kb": 3300, "psram_total_kb": 8192,
  "heap_largest_kb": 61, "audio_in_hz": 16000, "audio_out_hz": 24000,
  "server": "http://192.168.1.20:8003/xiaozhi/ota/", "server_custom": true
}
```

| Field | Meaning |
|---|---|
| `state` | Device state index: 0 unknown, 1 starting, 2 wifi setup, 3 idle, 4 connecting, 5 listening, 6 speaking, 7 notifying, 8 upgrading, 9 activating, 10 testing audio, 11 fatal error |
| `napping` | Light standby is on (screen off, 160 MHz, WiFi and wake word still on) |
| `power` | `"console"` when a PC is attached over USB, `"battery"` when the robot is online without one (a plain USB charger also reads `battery`) |
| `cpu_load` | Percent, averaged since the previous call |
| `fps` | Screen redraws per second since the previous call; 0 when the screen is static |
| `heap_largest_kb` | Largest free block of internal memory |
| `rssi` | WiFi signal in dBm |
| `server`, `server_custom` | The voice server's OTA URL in use, and whether it is an own server (`true`) or the built-in default cloud (`false`) |
| `volume`, `volume_requested`, `volume_cap` | What the speaker plays at, what was asked for, and the limit in force (100, or 40 during quiet hours). `volume` = the lower of the other two |
| `panel_url` | Address of the Jarvis backend control panel (`http://<server host>:8090/`) when an own server is set, otherwise `""`. The settings page shows an "Advanced" button for it (next to "Jarvis settings" at the top) |

Older firmware may leave out newer fields (`cpu_load`, `fps`, `heap_largest_kb`, `audio_*`, `camera_*`,
`board_name`, `power`); clients should treat every field as optional.

## GET /api/settings

An array. Every item has `key`, `kind`, `help` and `value`; the rest depends on `kind`:

| `kind` | `value` | Extra fields |
|---|---|---|
| `int` | number | `min`, `max`, `step` |
| `hundredths` | number, two decimals | `min`, `max`, `step` (0.01) |
| `bool` | `true` / `false` | |
| `time` | `"HH:MM"` or `null` (= off) | |
| `enum` | string | `options` (array of strings) |
| `text` | string | `max_length` |

Some settings exist on the robot but are not offered by the page or the app: `motor_max_speed` (fixed at
100%) and `shutter_sound` (fixed on). Settings the clients do not know are listed under "Other".

## POST /api/settings

Body: `{"key": "wake_threshold", "value": "0.55"}`. **`value` is always a string**, also for numbers
and booleans (`"1"` / `"0"`), and `"off"` clears a `time` setting.

Success: `{"ok": true, "message": "...", "settings": [ <the updated item> ]}`.
Rejected: `{"ok": false, "message": "wake_threshold must be 0.50 to 0.95"}` (still HTTP 200). A body that
is not `{"key": string, "value": string}` gives HTTP 400.

## POST /api/reset

No body. Reply `{"ok": true, "message": "All settings reset to defaults."}`.

## POST /api/drive?l=-100..100&r=-100..100

Sets the left and right wheel speed in percent (negative = backwards; values outside -100..100 are
clamped). Empty `200` reply. **Each command only lasts 500 ms**, so a client that is driving must send it
again about every 150 ms; if the commands stop (button released, WiFi lost, app closed) the robot stops by
itself. `l=0&r=0` stops immediately and cancels any queued movement.

## POST /api/power?action=...

| `action` | Extra | Effect |
|---|---|---|
| `nap` | | Light standby, starts about 2 s later |
| `mute` / `unmute` | | The microphone reads silence until unmuted or until the robot restarts (nothing is saved; `muted` in `/api/status`). The speaker stays on |
| `follow_on` / `follow_off` | | Follow mode (the `follow_mode` setting, always off after a restart): while Jarvis is idle it keeps turning on the spot towards your face. Needs the own voice server; reported as `follow` in `/api/status` (firmware build 81 and newer) |
| `face` | | Looks at you once: one picture, the own server finds the face, up to three short full-power turns until Jarvis faces it (about 3 to 8 s, the answer comes at once). Needs the own voice server |
| `wake` | | Leaves the nap |
| `deepsleep` | `minutes=0..1440` | Everything off including WiFi, starts about 2 s later; `0` = until the BOOT button is pressed. Only the timer or the BOOT button wakes the robot; this API cannot. |

Reply `{"ok": true, "message": "..."}`; an unknown `action` or `minutes` outside 0..1440 gives HTTP 400.

## POST /api/server

Body (JSON): `{"server": "192.168.1.20"}`. The value is `"default"` (back to the xiaozhi.me cloud), an IPv4 address or LAN
host name, optionally with `:port` (default `8003`; the robot then asks `http://<host>:<port>/xiaozhi/ota/`).

Only addresses on your own network are accepted here (10.x.x.x, 172.16-31.x.x, 192.168.x.x, a name without dots, `.local`, `.lan`):
the page has no login and the robot streams its microphone to the server, so someone on your WiFi must not be able to
send it to a host on the internet. A full URL or any other host can only be set from the USB console (`!server <value>`;
`!server check <value>` shows what would be accepted without saving).

Reply `{"ok": true, "message": "...", "server": "...", "server_custom": true}` and the robot restarts about 2 s later; a
refused value gives `{"ok": false, "message": "<reason>"}`, a malformed body HTTP 400.

## POST /api/volume?value=0..100

Sets the requested speaker volume (saved; the same value "turn the volume up" changes). The speaker plays at the lower of
this and the night-mode limit (quiet hours), so the reply tells you what it works out to:
`{"ok": true, "volume_requested": 90, "volume": 78, "volume_cap": 78}`. A value outside 0..100 gives HTTP 400.
