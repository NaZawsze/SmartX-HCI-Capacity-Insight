import re
import subprocess

filepath = "/opt/smartx-storage-forecast/frontend/src/styles/global.css"

try:
    with open(filepath, "r") as f:
        css = f.read()

    # 1. Update :root variables
    root_vars = """
  --active-bg: linear-gradient(135deg, rgba(22, 119, 255, 0.1), rgba(22, 119, 255, 0.02));
  --active-border: 1px solid rgba(22, 119, 255, 0.2);
  --active-shadow: 0 4px 12px rgba(22, 119, 255, 0.08);
  --card-shadow: 0 8px 24px var(--shadow-color), inset 0 1px 0 rgba(255, 255, 255, 0.8), inset 1px 0 0 rgba(255, 255, 255, 0.4);
"""
    css = re.sub(r'(--input-bg:\s*rgba\(255, 255, 255, 0\.8\);)', r'\1' + root_vars, css)

    # 2. Update dark mode variables
    dark_vars = """
  --active-bg: linear-gradient(135deg, rgba(0, 229, 255, 0.2), rgba(0, 184, 212, 0.05));
  --active-border: 1px solid rgba(0, 229, 255, 0.3);
  --active-shadow: 0 0 20px rgba(0, 229, 255, 0.15);
  --card-shadow: 0 8px 24px var(--shadow-color), inset 0 1px 0 rgba(255, 255, 255, 0.05);
"""
    css = re.sub(r'(--input-bg:\s*rgba\(15, 23, 42, 0\.4\);)', r'\1' + dark_vars, css)

    # 3. Update --glass-border
    css = re.sub(r'--glass-border:\s*1px solid rgba\(255, 255, 255, 0\.8\);', '--glass-border: 1px solid var(--line);', css)
    css = re.sub(r'--glass-border:\s*1px solid rgba\(255, 255, 255, 0\.08\);', '--glass-border: 1px solid var(--line);', css)

    # 4. Update .sidebar-active-card
    css = re.sub(
        r'background:\s*linear-gradient\(135deg,\s*rgba\(0, 229, 255, 0\.2\),\s*rgba\(0, 184, 212, 0\.05\)\);\s*border:\s*1px solid rgba\(0, 229, 255, 0\.3\);\s*box-shadow:\s*0 0 20px rgba\(0, 229, 255, 0\.15\);',
        'background: var(--active-bg); border: var(--active-border); box-shadow: var(--active-shadow);',
        css
    )

    # 5. Update .card and .metric-card shadow
    css = re.sub(r'box-shadow:\s*0 8px 24px var\(--shadow-color\);', 'box-shadow: var(--card-shadow);', css)

    # 6. Update search box backgrounds
    css = re.sub(
        r'(\.scope-button,\s*\.search-box,\s*\.mini-search\s*\{[^}]*?)background:\s*rgba\(255, 255, 255, 0\.03\);',
        r'\1background: var(--input-bg);',
        css
    )

    # 7. Update cluster-select background
    css = re.sub(
        r'(\.cluster-select\s*\{[^}]*?)background:\s*rgba\(255, 255, 255, 0\.03\);',
        r'\1background: var(--input-bg);',
        css
    )

    with open(filepath, "w") as f:
        f.write(css)

    print("CSS Refined.")

    subprocess.run(["git", "add", "."], cwd="/opt/smartx-storage-forecast")
    subprocess.run(["git", "commit", "-m", "style: refine glassmorphism borders and shadows"], cwd="/opt/smartx-storage-forecast")
    subprocess.run(["docker-compose", "down"], cwd="/opt/smartx-storage-forecast")
    subprocess.run(["docker-compose", "up", "-d", "--build"], cwd="/opt/smartx-storage-forecast")
    print("Done")
except Exception as e:
    print("Error:", e)
