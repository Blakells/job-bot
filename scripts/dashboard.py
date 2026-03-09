#!/usr/bin/env python3
"""
Job Bot Dashboard v2 — Multi-User Support
Run with: python3 scripts/dashboard.py
Open: http://localhost:5050
"""

import json, os, sys
from pathlib import Path

try:
    from flask import Flask, jsonify, request, render_template_string
except ImportError:
    print("Installing flask...")
    os.system("{} -m pip install flask --break-system-packages -q".format(sys.executable))
    from flask import Flask, jsonify, request, render_template_string

app = Flask(__name__)
PROFILES_DIR = Path("profiles")
LOG_FILE = Path("outputs/application_log.json")


def get_all_profiles():
    profiles = []
    if not PROFILES_DIR.exists():
        return profiles
    for item in sorted(PROFILES_DIR.iterdir()):
        if not item.is_dir() or item.name.startswith("."):
            continue
        profile_path = item / "profile.json"
        jobs_path = item / "scored_jobs.json"
        info = {"dir_name": item.name, "display_name": item.name.title(),
                "has_profile": profile_path.exists(), "job_count": 0, "target_roles": []}
        if profile_path.exists():
            try:
                p = json.loads(profile_path.read_text())
                info["display_name"] = p.get("personal", {}).get("name", item.name.title())
                info["target_roles"] = p.get("target_roles", [])
            except Exception:
                pass
        if jobs_path.exists():
            try:
                info["job_count"] = len(json.loads(jobs_path.read_text()))
            except Exception:
                pass
        profiles.append(info)
    return profiles


def load_jobs(profile_name):
    for path in [PROFILES_DIR / profile_name / "scored_jobs.json",
                 PROFILES_DIR / "scored_jobs.json"]:
        if path.exists():
            try:
                return json.loads(path.read_text())
            except Exception:
                pass
    return []


def save_jobs(profile_name, jobs):
    path = PROFILES_DIR / profile_name / "scored_jobs.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(jobs, indent=2))


def load_profile(profile_name):
    path = PROFILES_DIR / profile_name / "profile.json"
    if path.exists():
        try:
            return json.loads(path.read_text())
        except Exception:
            pass
    return {}


def load_log():
    if LOG_FILE.exists():
        try:
            return json.loads(LOG_FILE.read_text())
        except Exception:
            pass
    return []


# Load HTML template
_template_path = Path(__file__).parent / "dashboard_template.html"
if _template_path.exists():
    HTML = _template_path.read_text()
else:
    HTML = "<h1>dashboard_template.html not found in scripts/ folder</h1>"


@app.route("/")
def index():
    return render_template_string(HTML)


@app.route("/api/profiles")
def api_profiles():
    return jsonify(get_all_profiles())


@app.route("/api/profile/<name>")
def api_profile(name):
    return jsonify(load_profile(name))


@app.route("/api/jobs/<name>", methods=["GET"])
def api_get_jobs(name):
    return jsonify(load_jobs(name))


@app.route("/api/jobs/<name>", methods=["POST"])
def api_save_jobs(name):
    save_jobs(name, request.get_json())
    return jsonify({"ok": True})


@app.route("/api/log")
def api_log():
    return jsonify(load_log())


def main():
    print("\n🚀 Job Bot Dashboard v2")
    print("=" * 40)
    profiles = get_all_profiles()
    if profiles:
        print("  Profiles found:")
        for p in profiles:
            print("    {} — {} jobs".format(p["display_name"], p["job_count"]))
    print("\n  Open: http://localhost:5050")
    print("  Press Ctrl+C to stop\n")
    app.run(host="0.0.0.0", port=5050, debug=False)


if __name__ == "__main__":
    main()
