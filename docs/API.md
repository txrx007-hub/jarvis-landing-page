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

## GET /api/status

```json
{
  "board": "wall-e-xiao/2.5.0", "board_name": "ESP32 S3 Sense",
  "camera_detected": true, "camera_sensor": "OV3660",
  "ssid": "HomeWiFi", "ip": "192.168.1.50", "mac": "AA:BB:CC:DD:EE:FF", "rssi": -51,
  "uptime_s": 946, "state": 3, "napping": false, "power": "battery",
  "cpu_load": 42, "cpu_mhz": 240, "fps": 27,
  "ram_free_kb": 71, "ram_total_kb": 399, "psram_free_kb": 3300, "psram_total_kb": 8192,
  "heap_largest_kb": 61, "audio_in_hz": 16000, "audio_out_hz": 24000
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
| `wake` | | Leaves the nap |
| `deepsleep` | `minutes=0..1440` | Everything off including WiFi, starts about 2 s later; `0` = until the BOOT button is pressed. Only the timer or the BOOT button wakes the robot; this API cannot. |

Reply `{"ok": true, "message": "..."}`; an unknown `action` or `minutes` outside 0..1440 gives HTTP 400.
