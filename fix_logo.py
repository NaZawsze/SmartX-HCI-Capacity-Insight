import re
import subprocess

filepath = "/opt/smartx-storage-forecast/frontend/src/styles/global.css"

with open(filepath, "r") as f:
    css = f.read()

# Restore original brand-mark
original_brand = """
.brand-mark {
  width: 24px;
  height: 24px;
  background: linear-gradient(135deg, #7bc2ff 10%, #1677ff 55%, #7fe0ff 100%);
  clip-path: polygon(15% 45%, 92% 5%, 64% 94%);
}
"""

css = re.sub(
    r'\.brand-mark\s*\{[^}]*clip-path:[^}]*\}',
    original_brand.strip(),
    css
)

with open(filepath, "w") as f:
    f.write(css)

print("Brand-mark restored.")

subprocess.run(["git", "add", "."], cwd="/opt/smartx-storage-forecast")
subprocess.run(["git", "commit", "-m", "fix: restore original SmartX brand logo color"], cwd="/opt/smartx-storage-forecast")
subprocess.run(["docker-compose", "down"], cwd="/opt/smartx-storage-forecast")
subprocess.run(["docker-compose", "up", "-d", "--build"], cwd="/opt/smartx-storage-forecast")
print("Done")
