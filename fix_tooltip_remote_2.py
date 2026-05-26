import re
import subprocess

filepath = "/opt/smartx-storage-forecast/frontend/src/components/TrendChart.tsx"

with open(filepath, "r") as f:
    code = f.read()

# First, fix the syntax error from the previous attempt if it exists
code = code.replace(
    r"<strong style=\"color:${actualTheme === \'dark\' ? \'#00e5ff\' : \'#1677ff\'}\">${formatBytes(item.value)}</strong>",
    '<strong style="color:${actualTheme === \'dark\' ? \'#00e5ff\' : \'#1677ff\'}">${formatBytes(item.value)}</strong>'
)

# If it's still the original hardcoded cyan, replace it properly
# Notice how I use double quotes around the python string to safely enclose single quotes for JS template literal
code = code.replace(
    '<strong style="color:#00e5ff">${formatBytes(item.value)}</strong>',
    '<strong style="color:${actualTheme === \'dark\' ? \'#00e5ff\' : \'#1677ff\'}">${formatBytes(item.value)}</strong>'
)

with open(filepath, "w") as f:
    f.write(code)

print("TrendChart.tsx tooltip text color fixed.")

subprocess.run(["git", "add", "."], cwd="/opt/smartx-storage-forecast")
subprocess.run(["git", "commit", "-m", "fix: trend chart tooltip text color in light theme"], cwd="/opt/smartx-storage-forecast")
subprocess.run(["docker-compose", "down"], cwd="/opt/smartx-storage-forecast")
subprocess.run(["docker-compose", "up", "-d", "--build"], cwd="/opt/smartx-storage-forecast")
print("Done")
