import re

with open("frontend/src/styles/global.css", "r") as f:
    css = f.read()

# Replace the current :root which is dark mode, with a new :root (light) and [data-theme="dark"]
new_root = """
:root {
  /* Light Mode Variables (Frosted Glass Aesthetic) */
  --blue: #1677ff;
  --blue-600: #0f66dd;
  --cyan: #16c7d3;
  --green: #21c875;
  --orange: #ff9f1c;
  --red: #ff5a5f;
  --ink: #102a56;
  --text: #26364f;
  --muted: #7a8aa0;
  --line: rgba(22, 119, 255, 0.1);
  --line-soft: rgba(22, 119, 255, 0.05);
  --panel: rgba(255, 255, 255, 0.65);
  --background: #f0f5fa;
  --sidebar: rgba(240, 245, 250, 0.8);
  --sidebar-width: 240px;
  --chrome-height: 64px;
  --glass-border: 1px solid rgba(255, 255, 255, 0.8);
  --bg-image: radial-gradient(circle at 50% 0%, #e0ebf8 0%, #f0f5fa 60%);
  --shadow-color: rgba(40, 72, 112, 0.08);
  --shadow-color-lg: rgba(40, 72, 112, 0.12);
  --input-bg: rgba(255, 255, 255, 0.8);
  
  font-family: "Outfit", "Inter", "PingFang SC", "Microsoft YaHei", Arial, sans-serif;
  color: var(--text);
  background: transparent;
  background-image: var(--bg-image);
  background-attachment: fixed;
}

[data-theme="dark"] {
  /* Dark Mode Variables (Neon Glassmorphism Aesthetic) */
  --blue: #00e5ff;
  --blue-600: #00b8d4;
  --cyan: #18ffff;
  --green: #00e676;
  --orange: #ff9100;
  --red: #ff1744;
  --ink: #e2e8f0;
  --text: #a0aec0;
  --muted: #718096;
  --line: rgba(255, 255, 255, 0.1);
  --line-soft: rgba(255, 255, 255, 0.05);
  --panel: rgba(15, 23, 42, 0.6);
  --background: #050b14;
  --sidebar: rgba(10, 15, 30, 0.7);
  --glass-border: 1px solid rgba(255, 255, 255, 0.08);
  --bg-image: radial-gradient(circle at 50% 0%, #0d1e3d 0%, #050b14 60%);
  --shadow-color: rgba(0, 0, 0, 0.4);
  --shadow-color-lg: rgba(0, 0, 0, 0.5);
  --input-bg: rgba(15, 23, 42, 0.4);
}
"""

css = re.sub(r':root\s*\{[^}]+\}', new_root.strip(), css)

# Replace specific hardcoded box-shadows to use variables so they switch correctly
css = re.sub(r'box-shadow:\s*0\s*12px\s*32px\s*rgba\(0,\s*0,\s*0,\s*0\.5\)', 'box-shadow: 0 12px 32px var(--shadow-color-lg)', css)
css = re.sub(r'box-shadow:\s*0\s*8px\s*24px\s*rgba\(0,\s*0,\s*0,\s*0\.4\)', 'box-shadow: 0 8px 24px var(--shadow-color)', css)
css = re.sub(r'background:\s*#fff;', 'background: var(--input-bg);', css) # inputs background

with open("frontend/src/styles/global.css", "w") as f:
    f.write(css)

print("global.css theme variables applied.")
