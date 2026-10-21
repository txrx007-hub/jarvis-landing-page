#!/usr/bin/env python3
"""A fake Jarvis robot, so the landing page (and the Android app) can be developed without hardware.

    python mock/mock_robot.py [port] [own]  # default port 8080; "own": the robot uses an own backend (and this fake plays that backend's panel, so the Music card shows)
    open http://127.0.0.1:8080/

Serves ../index.html and the same /api/* endpoints as the firmware (see docs/API.md). Settings you
change are kept in memory, "nap" / "deep sleep" change the reported status, and /api/drive remembers
the last wheel command. Plain Python 3 standard library, no installs.

Add ?shot=<name> to the page URL to get the page with a small script appended that sets up a state
for screenshots (used by mock/screenshots.py); the real index.html is never modified.
"""
import copy
import json
import os
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
PAGE = os.path.join(HERE, "..", "index.html")

DEFAULT_SETTINGS = [
    {"key": "motor_trim", "kind": "int", "help": "wheel balance: raise it if Jarvis drifts left, lower it if it drifts right", "min": -20, "max": 20, "step": 1, "value": 0},
    {"key": "turn_ms_per_90", "kind": "int", "help": "milliseconds for a 90 degree turn at speed 60", "min": 100, "max": 3000, "step": 10, "value": 600},
    {"key": "motor_a_invert", "kind": "bool", "help": "reverses motor A (right wheel)", "value": False},
    {"key": "motor_b_invert", "kind": "bool", "help": "reverses motor B (left wheel)", "value": False},
    {"key": "motor_swap", "kind": "bool", "help": "swaps the left and right motors", "value": False},
    {"key": "soft_start_ms", "kind": "int", "help": "ramp-up time that limits current spikes", "min": 0, "max": 1000, "step": 10, "value": 200},
    {"key": "mic_gain_db", "kind": "int", "help": "software microphone gain in dB", "min": 0, "max": 24, "step": 1, "value": 18},
    {"key": "wake_threshold", "kind": "hundredths", "help": "wake word threshold, lower wakes more easily", "min": 0.5, "max": 0.95, "step": 0.01, "value": 0.52},
    {"key": "wake_chirp", "kind": "bool", "help": "short chirp right after the wake word", "value": True},
    {"key": "idle_clock_min", "kind": "int", "help": "minutes of idle before the clock shows", "min": 0, "max": 60, "step": 1, "value": 5},
    {"key": "quiet_start", "kind": "time", "help": "night mode start, HH:MM or off", "value": "22:30"},
    {"key": "quiet_end", "kind": "time", "help": "night mode end, HH:MM or off", "value": None},
    {"key": "weather_city", "kind": "text", "help": "city for the weather line on the idle clock", "max_length": 40, "value": "Amsterdam"},
    {"key": "visualizer_mode", "kind": "enum", "help": "what the screen shows while Jarvis speaks", "value": "rainbow",
     "options": ["off", "winamp", "scope", "radial", "vu", "mouth", "orb", "rainbow"]},
    {"key": "music_icon", "kind": "enum", "help": "the picture that replaces the eyes while music plays", "value": "music icon 1",
     "options": ["music icon 1", "music icon 2"]},
    {"key": "log_level", "kind": "enum", "help": "serial log detail", "value": "warn", "options": ["error", "warn", "info", "debug"]},
]

DEFAULT_SERVER = "https://api.example.invalid/xiaozhi/ota/"  # stands in for the built-in cloud URL
STATE = {"settings": copy.deepcopy(DEFAULT_SETTINGS), "napping": False, "started": time.time(), "drive": (0, 0, 0.0),
         "server": "", "playing": True}  # "" = built-in default (cloud)


def private_host(host):
    """Same rule as the firmware's web page: 10/8, 172.16/12, 192.168/16 or a LAN name."""
    parts = host.split(".")
    if all(p.isdigit() for p in parts) and len(parts) == 4:
        a, b = int(parts[0]), int(parts[1])
        return a == 10 or (a == 172 and 16 <= b <= 31) or (a == 192 and b == 168)
    return "." not in host or host.endswith((".local", ".lan"))

# Page states for screenshots (?shot=...): name -> (script run after the page loaded, window height in px).
# Chrome's headless window cannot be narrower than ~500 px; the page's column is 480 px max anyway.
HIDE_TOP = "['info','power','server'].forEach(function(i){$(i).style.display='none';}); document.querySelector('.toggles').style.display='none';"
SHOTS = {
    "top-dark": ("setTheme('dark');", 860),
    "top-light": ("setTheme('light');", 860),
    "remote-dark": ("setTheme('dark'); $('remoteToggle').click(); ['up','right'].forEach(function(d){document.querySelector('.pad .'+d).classList.add('held');});", 1230),
    "power-light": ("setTheme('light'); $('deepBtn').click(); $('sleepH').value='3'; $('sleepM').value='25'; $('sleepH').dispatchEvent(new Event('input'));", 1000),
    "settings-dark": ("setTheme('dark'); " + HIDE_TOP + " openGroup('Motors'); openGroup('Audio and wake word');", 1180),
    "settings-light": ("setTheme('light'); " + HIDE_TOP + " openGroup('Motors'); openGroup('Screen and quiet hours');", 1180),
    "voice-light": ("setTheme('light'); $('commandsToggle').click();", 1350),
    "music-dark": ("setTheme('dark'); ['info','power','server'].forEach(function(i){$(i).style.display='none';}); document.querySelector('.toggles').style.display='none';", 520),
}
SHOT_PRELUDE = """
function $(id){return document.getElementById(id);}
function setTheme(t){document.documentElement.setAttribute('data-theme',t); var s=$('themeSwitch'); if(s) s.checked=(t==='light');}
function openGroup(title){var b=Array.prototype.find.call(document.querySelectorAll('button.group-toggle'),function(x){return x.firstChild.textContent===title;}); if(b) b.click();}
"""


def volume_cap():
    return 100  # no cap any more (night mode would lower it)


def volume_requested():
    return STATE.get("volume", 70)


def status(host=""):
    s = STATE
    return {
        "board": "wall-e-xiao/2.5.0", "board_name": "ESP32 S3 Sense", "camera_detected": True, "camera_sensor": "OV3660",
        "ssid": "HomeWiFi", "ip": "192.168.1.50", "mac": "AA:BB:CC:DD:EE:FF", "rssi": -51,
        "uptime_s": int(time.time() - s["started"]) + 946, "state": 3, "napping": s["napping"],
        "cpu_load": 42, "fps": 27, "heap_largest_kb": 61, "audio_in_hz": 16000, "audio_out_hz": 24000,
        "power": "battery", "cpu_mhz": 160 if s["napping"] else 240,
        "ram_free_kb": 71, "ram_total_kb": 399, "psram_free_kb": 3300, "psram_total_kb": 8192,
        "server": s["server"] or DEFAULT_SERVER, "server_custom": bool(s["server"]),
        "volume": min(volume_requested(), volume_cap()), "volume_requested": volume_requested(), "volume_cap": volume_cap(),
        # the real robot points at the backend's control panel; the fake one plays that panel too (see the /music.js and /ha.js routes below)
        "panel_url": ("http://%s/" % host) if host else "",
    }


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        sys.stderr.write("%s %s\n" % (self.command, self.path))

    def _send(self, body, ctype="application/json", code=200):
        data = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        url = urlparse(self.path)
        if url.path in ("/", "/index.html"):
            html = open(PAGE, encoding="utf-8").read()
            shot = parse_qs(url.query).get("shot", [None])[0]
            if shot in SHOTS:
                script = "<script>window.addEventListener('load',function(){setTimeout(function(){%s%s},900);});</script>" % (SHOT_PRELUDE, SHOTS[shot][0])
                html = html.replace("</body>", script + "</body>")
            self._send(html, "text/html; charset=utf-8")
        elif url.path == "/api/status":
            self._send(json.dumps(status(self.headers.get("Host", ""))))
        elif url.path in ("/music.js", "/ha.js", "/pin.js", "/music-do.js"):   # what the backend's control panel would answer (made-up song)
            now = {"title": "Sunrise Boulevard", "artist": "Neon Harbour"} if STATE["playing"] else None
            body = {"/music.js": "window.JARVIS_MUSIC = %s;" % json.dumps({"on": True, "now": now}),
                    "/ha.js": 'window.JARVIS_HA = {"ok": true};',
                    "/pin.js": 'window.JARVIS_PANEL_PIN = "";',
                    "/music-do.js": 'window.JARVIS_MUSIC_DO = {"ok": true};'}[url.path]
            self._send(body, "application/javascript; charset=utf-8")
        elif url.path == "/api/settings":
            self._send(json.dumps(STATE["settings"]))
        elif url.path == "/api/ping":
            self._send(b"", "text/plain")
        elif url.path == "/api/net":   # made-up traffic that grows like a robot that is talking now and then
            t = int((time.time() - STATE["started"]) * 1000)
            pk = t // 20
            self._send(json.dumps({"tx_pkts": pk * 2, "rx_pkts": pk * 3, "tx_bytes": pk * 2 * 180, "rx_bytes": pk * 3 * 260, "t_ms": t}))
        else:
            self._send(b"not found", "text/plain", 404)

    def do_POST(self):
        url = urlparse(self.path)
        q = parse_qs(url.query)
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b""
        if url.path == "/api/settings":
            try:
                req = json.loads(body)
                key, value = req["key"], req["value"]
                item = next(s for s in STATE["settings"] if s["key"] == key)
            except Exception:
                return self._send(json.dumps({"ok": False, "message": "unknown setting or bad request"}))
            kind = item["kind"]
            try:
                if kind == "int":
                    v = int(value)
                    assert item["min"] <= v <= item["max"]
                elif kind == "hundredths":
                    v = round(float(value), 2)
                    assert item["min"] <= v <= item["max"]
                elif kind == "bool":
                    v = value in ("1", "true", "on")
                elif kind == "time":
                    v = None if value == "off" else value
                else:
                    v = value
            except Exception:
                return self._send(json.dumps({"ok": False, "message": "%s: value out of range" % key}))
            item["value"] = v
            self._send(json.dumps({"ok": True, "message": "%s set to %s" % (key, v), "settings": [item]}))
        elif url.path == "/api/reset":
            STATE["settings"] = copy.deepcopy(DEFAULT_SETTINGS)
            self._send(json.dumps({"ok": True, "message": "All settings reset to defaults."}))
        elif url.path == "/api/volume":
            try:
                value = int(q.get("value", [""])[0])
                assert 0 <= value <= 100
            except Exception:
                return self._send(b"value must be 0 to 100", "text/plain", 400)
            STATE["volume"] = value
            self._send(json.dumps({"ok": True, "volume_requested": value, "volume": min(value, volume_cap()), "volume_cap": volume_cap()}))
        elif url.path == "/api/server":
            try:
                value = str(json.loads(body)["server"]).strip()
            except Exception:
                return self._send(b'expected {"server": "192.168.x.y" or "default"}', "text/plain", 400)
            if value in ("", "default"):
                STATE["server"] = ""
                msg = "Server set to the built-in default (xiaozhi.me cloud)."
            elif "://" in value:
                return self._send(json.dumps({"ok": False, "message": "Enter an IP address or LAN name, not a full URL."}))
            else:
                host, _, port = value.partition(":")
                if not host or (port and not (port.isdigit() and 1 <= int(port) <= 65535)):
                    return self._send(json.dumps({"ok": False, "message": "not a valid IP address or host name"}))
                if not private_host(host):
                    return self._send(json.dumps({"ok": False, "message": "From the web page only a LAN address is accepted."}))
                STATE["server"] = "http://%s:%s/xiaozhi/ota/" % (host, port or "8003")
                msg = "Server set to " + STATE["server"]
            self._send(json.dumps({"ok": True, "message": msg + " Restarting in 2 s.", "server": STATE["server"] or DEFAULT_SERVER,
                                   "server_custom": bool(STATE["server"])}))
        elif url.path == "/api/stop":
            STATE["playing"] = False
            self._send(json.dumps({"ok": True}))
        elif url.path == "/api/drive":
            STATE["drive"] = (int(q.get("l", ["0"])[0]), int(q.get("r", ["0"])[0]), time.time())
            self._send(b"", "text/plain")
        elif url.path == "/api/power":
            action = q.get("action", [""])[0]
            if action == "nap":
                STATE["napping"] = True
                self._send(json.dumps({"ok": True, "message": "Napping."}))
            elif action == "wake":
                STATE["napping"] = False
                self._send(json.dumps({"ok": True, "message": "Waking up."}))
            elif action == "deepsleep":
                minutes = int(q.get("minutes", ["0"])[0])
                if not 0 <= minutes <= 1440:
                    return self._send(b"minutes must be 0 to 1440", "text/plain", 400)
                self._send(json.dumps({"ok": True, "message": "Deep sleep in 2 s."}))
            else:
                self._send(b"action must be nap, wake or deepsleep", "text/plain", 400)
        else:
            self._send(b"not found", "text/plain", 404)


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
    if len(sys.argv) > 2 and sys.argv[2] == "own":   # as if the robot already talks to an own backend: the page then shows the backend's music and command lists
        STATE["server"] = "http://192.168.1.20:8003/xiaozhi/ota/"
    print("Fake Jarvis on http://127.0.0.1:%d/  (Ctrl+C to stop)" % port)
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
