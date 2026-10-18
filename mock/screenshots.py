#!/usr/bin/env python3
"""Regenerates docs/screenshots/*.png: starts the fake robot and screenshots the page in headless
Edge or Chrome at phone width, in each state listed in mock_robot.SHOTS.

    python mock/screenshots.py [path-to-browser]
"""
import os
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.abspath(os.path.join(HERE, "..", "docs", "screenshots"))
PORT = 8765

CANDIDATES = [  # Chrome first: Edge's headless --screenshot is flaky
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    "/usr/bin/google-chrome", "/usr/bin/chromium", "/usr/bin/chromium-browser",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]


def find_browser():
    if len(sys.argv) > 1:
        return sys.argv[1]
    for c in CANDIDATES:
        if os.path.exists(c):
            return c
    return shutil.which("chromium") or shutil.which("google-chrome") or shutil.which("msedge")


def main():
    browser = find_browser()
    if not browser:
        sys.exit("No Edge/Chrome found; pass its path as the first argument.")
    sys.path.insert(0, HERE)
    import mock_robot

    os.makedirs(OUT, exist_ok=True)
    server = subprocess.Popen([sys.executable, os.path.join(HERE, "mock_robot.py"), str(PORT)],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(1.2)
    try:
        profile = tempfile.mkdtemp(prefix="jarvis-shots-")  # own profile: a running browser would swallow the run
        for name, (_script, height) in mock_robot.SHOTS.items():
            target = os.path.join(OUT, "landing-%s.png" % name)
            subprocess.run([
                browser, "--headless=new", "--user-data-dir=" + profile, "--no-first-run",
                "--disable-gpu", "--hide-scrollbars",
                "--force-device-scale-factor=2", "--window-size=500,%d" % height,
                "--virtual-time-budget=7000", "--screenshot=" + target,
                "http://127.0.0.1:%d/?shot=%s" % (PORT, name),
            ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if not os.path.exists(target):
                sys.exit("The browser did not write " + target)
            print("wrote", target)
    finally:
        server.terminate()
        shutil.rmtree(profile, ignore_errors=True)


if __name__ == "__main__":
    main()
