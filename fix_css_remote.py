import re
import os
import subprocess

filepath = "/opt/smartx-storage-forecast/frontend/src/styles/global.css"
with open(filepath, "r") as f:
    css = f.read()

# Fix button inheriting color
css = re.sub(
    r'button,\s*input\s*\{\s*font:\s*inherit;\s*\}',
    r'button,\ninput {\n  font: inherit;\n  color: inherit;\n}',
    css
)

# Fix sidebar-active-card text color
css = re.sub(
    r'(\.sidebar-active-card\s*\{[^}]*?)color:\s*#ffffff;',
    r'\1color: var(--ink);',
    css
)

# Fix sidebar-active-status text color
css = re.sub(
    r'(\.sidebar-active-status\s*\{[^}]*?)color:\s*#d8ebff;',
    r'\1color: var(--muted);',
    css
)

# Fix metric-value text color
css = re.sub(
    r'(\.metric-value\s*\{[^}]*?)color:\s*#ffffff;',
    r'\1color: var(--ink);',
    css
)

with open(filepath, "w") as f:
    f.write(css)

print("CSS fixed.")

# Commit and rebuild
print("Restarting service...")
subprocess.run(["git", "add", "."], cwd="/opt/smartx-storage-forecast")
subprocess.run(["git", "commit", "-m", "fix: text color in light/dark theme"], cwd="/opt/smartx-storage-forecast")
subprocess.run(["docker-compose", "down"], cwd="/opt/smartx-storage-forecast")
subprocess.run(["docker-compose", "up", "-d", "--build"], cwd="/opt/smartx-storage-forecast")
print("Done")
