import re
import subprocess
import os

print("Fixing TS errors on beta branch...")

# Checkout beta branch
subprocess.run(["git", "checkout", "beta"], check=True, cwd="/opt/smartx-storage-forecast")

def patch_file(filepath, component_name):
    try:
        with open(filepath, "r") as f:
            content = f.read()
            
        # Add actualTheme to Props interface
        if "actualTheme?:" not in content:
            content = re.sub(
                r'(interface ' + component_name + r'Props\s*\{)',
                r'\1\n  actualTheme?: "light" | "dark";',
                content
            )
            
            # Also accept it in component args if not there
            # export function DashboardPage({ summary, scope, onSummary, onSelectVm }: DashboardPageProps) {
            if "actualTheme =" not in content and "actualTheme=" not in content:
                content = re.sub(
                    r'(export function ' + component_name + r'\([^)]*)\)',
                    r'\1, actualTheme = "light" )',
                    content
                )
            
            with open(filepath, "w") as f:
                f.write(content)
            print(f"Patched {filepath}")
    except Exception as e:
        print(f"Failed to patch {filepath}: {e}")

base_path = "/opt/smartx-storage-forecast/frontend/src/pages/"
patch_file(base_path + "DashboardPage.tsx", "DashboardPage")
patch_file(base_path + "VmsPage.tsx", "VmsPage")
patch_file(base_path + "ReportsPage.tsx", "ReportsPage")

# Check if App.tsx needs fixing (e.g. actualTheme not passed correctly)
app_path = "/opt/smartx-storage-forecast/frontend/src/App.tsx"
with open(app_path, "r") as f:
    app_ts = f.read()
if "actualTheme={actualTheme}" not in app_ts:
    app_ts = app_ts.replace('<DashboardPage ', '<DashboardPage actualTheme={actualTheme} ')
    app_ts = app_ts.replace('<VmsPage ', '<VmsPage actualTheme={actualTheme} ')
    app_ts = app_ts.replace('<ReportsPage ', '<ReportsPage actualTheme={actualTheme} ')
    with open(app_path, "w") as f:
        f.write(app_ts)

# Commit the fix
subprocess.run(["git", "add", "."], cwd="/opt/smartx-storage-forecast")
subprocess.run(["git", "commit", "-m", "fix: add actualTheme to page props"], cwd="/opt/smartx-storage-forecast")

# Restart service
print("Restarting service...")
subprocess.run(["docker-compose", "down"], cwd="/opt/smartx-storage-forecast")
subprocess.run(["docker-compose", "up", "-d", "--build"], cwd="/opt/smartx-storage-forecast")
print("Service restarted.")
