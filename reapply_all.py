import os
import re
import subprocess

print("Reapplying all theme patches...")

# 1. global.css
css_path = "/opt/smartx-storage-forecast/frontend/src/styles/global.css"
with open(css_path, "r") as f:
    css = f.read()

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
css = re.sub(r'box-shadow:\s*0\s*12px\s*32px\s*rgba\(0,\s*0,\s*0,\s*0\.5\)', 'box-shadow: 0 12px 32px var(--shadow-color-lg)', css)
css = re.sub(r'box-shadow:\s*0\s*8px\s*24px\s*rgba\(0,\s*0,\s*0,\s*0\.4\)', 'box-shadow: 0 8px 24px var(--shadow-color)', css)
css = re.sub(r'background:\s*#fff;', 'background: var(--input-bg);', css)
with open(css_path, "w") as f:
    f.write(css)

# 2. useTheme.ts
theme_hook = """import { useEffect, useState } from "react";
export type ThemeType = "light" | "dark" | "system";
export function useTheme() {
  const [theme, setThemeState] = useState<ThemeType>(() => {
    return (localStorage.getItem("ui-theme") as ThemeType) || "system";
  });
  const [actualTheme, setActualTheme] = useState<"light" | "dark">("light");

  useEffect(() => {
    const root = window.document.documentElement;
    const mediaQuery = window.matchMedia("(prefers-color-scheme: dark)");
    function applyTheme(targetTheme: ThemeType) {
      let resolvedTheme: "light" | "dark" = "light";
      if (targetTheme === "system") {
        resolvedTheme = mediaQuery.matches ? "dark" : "light";
      } else {
        resolvedTheme = targetTheme;
      }
      setActualTheme(resolvedTheme);
      if (resolvedTheme === "dark") {
        root.setAttribute("data-theme", "dark");
      } else {
        root.removeAttribute("data-theme");
      }
    }
    applyTheme(theme);
    const listener = () => applyTheme(theme);
    mediaQuery.addEventListener("change", listener);
    return () => mediaQuery.removeEventListener("change", listener);
  }, [theme]);

  const setTheme = (newTheme: ThemeType) => {
    localStorage.setItem("ui-theme", newTheme);
    setThemeState(newTheme);
  };
  return { theme, setTheme, actualTheme };
}
"""
os.makedirs("/opt/smartx-storage-forecast/frontend/src/hooks", exist_ok=True)
with open("/opt/smartx-storage-forecast/frontend/src/hooks/useTheme.ts", "w") as f:
    f.write(theme_hook)

# 3. TS interfaces
def patch_page_props(filepath, component_name):
    try:
        with open(filepath, "r") as f:
            content = f.read()
        if "actualTheme?:" not in content:
            content = re.sub(r'(interface ' + component_name + r'Props\s*\{)', r'\1\n  actualTheme?: "light" | "dark";', content)
            if "actualTheme =" not in content and "actualTheme=" not in content:
                content = re.sub(r'(export function ' + component_name + r'\([^)]*)\)', r'\1, actualTheme = "light" )', content)
            with open(filepath, "w") as f:
                f.write(content)
    except:
        pass
base_path = "/opt/smartx-storage-forecast/frontend/src/pages/"
patch_page_props(base_path + "DashboardPage.tsx", "DashboardPage")
patch_page_props(base_path + "VmsPage.tsx", "VmsPage")
patch_page_props(base_path + "ReportsPage.tsx", "ReportsPage")

# 4. App.tsx
app_path = "/opt/smartx-storage-forecast/frontend/src/App.tsx"
with open(app_path, "r") as f:
    app_ts = f.read()
if "useTheme" not in app_ts:
    app_ts = app_ts.replace('import { AppLayout } from "./components/AppLayout";', 'import { AppLayout } from "./components/AppLayout";\nimport { useTheme } from "./hooks/useTheme";')
if "const { theme, setTheme, actualTheme } = useTheme();" not in app_ts:
    app_ts = app_ts.replace('const [activePage, setActivePage] = useState<PageKey>("dashboard");', 'const [activePage, setActivePage] = useState<PageKey>("dashboard");\n  const { theme, setTheme, actualTheme } = useTheme();')
if "theme={theme}" not in app_ts:
    app_ts = app_ts.replace('<AppLayout activePage={activePage}', '<AppLayout activePage={activePage} theme={theme} onThemeChange={setTheme}')
if "actualTheme={actualTheme}" not in app_ts:
    app_ts = app_ts.replace('<DashboardPage ', '<DashboardPage actualTheme={actualTheme} ')
    app_ts = app_ts.replace('<VmsPage ', '<VmsPage actualTheme={actualTheme} ')
    app_ts = app_ts.replace('<ReportsPage ', '<ReportsPage actualTheme={actualTheme} ')
with open(app_path, "w") as f:
    f.write(app_ts)

# 5. AppLayout.tsx
layout_path = "/opt/smartx-storage-forecast/frontend/src/components/AppLayout.tsx"
with open(layout_path, "r") as f:
    layout_ts = f.read()
if "theme?: ThemeType" not in layout_ts:
    layout_ts = layout_ts.replace('import { Bell, Building2, ChevronDown, CircleCheck, ClipboardList, Database, HardDrive, KeyRound, LayoutDashboard, LogOut, Save, Search, Server, Settings, UserRound, View, X } from "lucide-react";',
                                  'import { Bell, Building2, ChevronDown, CircleCheck, ClipboardList, Database, HardDrive, KeyRound, LayoutDashboard, LogOut, Save, Search, Server, Settings, UserRound, View, X, Moon, Sun, Monitor } from "lucide-react";\nimport type { ThemeType } from "../hooks/useTheme";')
    layout_ts = layout_ts.replace('children: ReactNode;', 'children: ReactNode;\n  theme?: ThemeType;\n  onThemeChange?: (theme: ThemeType) => void;')
    layout_ts = layout_ts.replace('summary, children }: AppLayoutProps) {', 'summary, children, theme = "system", onThemeChange }: AppLayoutProps) {')
    layout_ts = layout_ts.replace('const [accountMenuOpen, setAccountMenuOpen] = useState(false);', 'const [accountMenuOpen, setAccountMenuOpen] = useState(false);\n  const [themeMenuOpen, setThemeMenuOpen] = useState(false);')
    theme_menu = """
            <div className="account-menu-wrap">
              <button className="icon-button" type="button" onClick={() => setThemeMenuOpen((open) => !open)} aria-haspopup="menu" aria-expanded={themeMenuOpen} title="主题设置">
                {theme === "light" ? <Sun size={17} /> : theme === "dark" ? <Moon size={17} /> : <Monitor size={17} />}
              </button>
              {themeMenuOpen && (
                <div className="account-menu" role="menu" style={{ right: "40px" }}>
                  <button type="button" role="menuitem" onClick={() => { onThemeChange?.("light"); setThemeMenuOpen(false); }}>
                    <Sun size={15} />
                    <span>浅色模式</span>
                  </button>
                  <button type="button" role="menuitem" onClick={() => { onThemeChange?.("dark"); setThemeMenuOpen(false); }}>
                    <Moon size={15} />
                    <span>深色模式</span>
                  </button>
                  <button type="button" role="menuitem" onClick={() => { onThemeChange?.("system"); setThemeMenuOpen(false); }}>
                    <Monitor size={15} />
                    <span>跟随系统</span>
                  </button>
                </div>
              )}
            </div>
"""
    layout_ts = layout_ts.replace('<div className="account-menu-wrap">', theme_menu + '            <div className="account-menu-wrap">')
    with open(layout_path, "w") as f:
        f.write(layout_ts)

# 6. Charts
trend_path = "/opt/smartx-storage-forecast/frontend/src/components/TrendChart.tsx"
with open(trend_path, "r") as f:
    trend_ts = f.read()
if "actualTheme?: \"light\" | \"dark\"" not in trend_ts:
    trend_ts = trend_ts.replace('export function TrendChart({ points, referenceValue, height = 280 }: TrendChartProps) {',
                                'export function TrendChart({ points, referenceValue, height = 280, actualTheme = "light" }: TrendChartProps & { actualTheme?: "light" | "dark" }) {')
    trend_ts = trend_ts.replace('backgroundColor: "rgba(15, 23, 42, 0.8)",', 'backgroundColor: actualTheme === "dark" ? "rgba(15, 23, 42, 0.8)" : "rgba(255, 255, 255, 0.9)",')
    trend_ts = trend_ts.replace('borderColor: "rgba(0, 229, 255, 0.3)",', 'borderColor: actualTheme === "dark" ? "rgba(0, 229, 255, 0.3)" : "rgba(22, 119, 255, 0.2)",')
    trend_ts = trend_ts.replace('textStyle: { color: "#e2e8f0" },', 'textStyle: { color: actualTheme === "dark" ? "#e2e8f0" : "#26364f" },')
    trend_ts = trend_ts.replace('axisLine: { lineStyle: { color: "rgba(255, 255, 255, 0.1)" } },', 'axisLine: { lineStyle: { color: actualTheme === "dark" ? "rgba(255, 255, 255, 0.1)" : "rgba(22, 119, 255, 0.1)" } },')
    trend_ts = trend_ts.replace('splitLine: { lineStyle: { color: "rgba(255, 255, 255, 0.05)" } }', 'splitLine: { lineStyle: { color: actualTheme === "dark" ? "rgba(255, 255, 255, 0.05)" : "rgba(22, 119, 255, 0.05)" } }')
    trend_ts = trend_ts.replace('itemStyle: { color: "#00e5ff", borderColor: "#fff", borderWidth: 2 },', 'itemStyle: { color: actualTheme === "dark" ? "#00e5ff" : "#1677ff", borderColor: "#fff", borderWidth: 2 },')
    trend_ts = trend_ts.replace('{ offset: 0, color: "rgba(0, 229, 255, 0.4)" }', '{ offset: 0, color: actualTheme === "dark" ? "rgba(0, 229, 255, 0.4)" : "rgba(22, 119, 255, 0.2)" }')
    trend_ts = trend_ts.replace('{ offset: 1, color: "rgba(0, 229, 255, 0.01)" }', '{ offset: 1, color: actualTheme === "dark" ? "rgba(0, 229, 255, 0.01)" : "rgba(22, 119, 255, 0.02)" }')
    trend_ts = trend_ts.replace('color: "#00e5ff",', 'color: actualTheme === "dark" ? "#00e5ff" : "#1677ff",')
    trend_ts = trend_ts.replace('shadowColor: "rgba(0, 229, 255, 0.5)",', 'shadowColor: actualTheme === "dark" ? "rgba(0, 229, 255, 0.5)" : "rgba(22, 119, 255, 0.3)",')
    with open(trend_path, "w") as f:
        f.write(trend_ts)

cluster_path = "/opt/smartx-storage-forecast/frontend/src/components/ClusterCapacityChart.tsx"
with open(cluster_path, "r") as f:
    cluster_ts = f.read()
if "actualTheme?: \"light\" | \"dark\"" not in cluster_ts:
    cluster_ts = cluster_ts.replace('export function ClusterCapacityChart({ clusters, title, height = 360 }: ClusterCapacityChartProps) {',
                                    'export function ClusterCapacityChart({ clusters, title, height = 360, actualTheme = "light" }: ClusterCapacityChartProps & { actualTheme?: "light" | "dark" }) {')
    cluster_ts = cluster_ts.replace('color: ["#00e5ff", "#a0aec0", "#e2e8f0", "#ff9100", "#ff1744"],', 
                                    'color: actualTheme === "dark" ? ["#00e5ff", "#a0aec0", "#e2e8f0", "#ff9100", "#ff1744"] : ["#1677ff", "#7a8aa0", "#26364f", "#ff9f1c", "#ff5a5f"],')
    cluster_ts = cluster_ts.replace('textStyle: { color: "#a0aec0", fontSize: 12 }', 'textStyle: { color: actualTheme === "dark" ? "#a0aec0" : "#7a8aa0", fontSize: 12 }')
    cluster_ts = cluster_ts.replace('backgroundColor: "rgba(15, 23, 42, 0.8)",', 'backgroundColor: actualTheme === "dark" ? "rgba(15, 23, 42, 0.8)" : "rgba(255, 255, 255, 0.9)",')
    cluster_ts = cluster_ts.replace('borderColor: "rgba(0, 229, 255, 0.3)",', 'borderColor: actualTheme === "dark" ? "rgba(0, 229, 255, 0.3)" : "rgba(22, 119, 255, 0.2)",')
    cluster_ts = cluster_ts.replace('textStyle: { color: "#e2e8f0" },', 'textStyle: { color: actualTheme === "dark" ? "#e2e8f0" : "#26364f" },')
    cluster_ts = cluster_ts.replace('axisLine: { lineStyle: { color: "rgba(255, 255, 255, 0.1)" } },', 'axisLine: { lineStyle: { color: actualTheme === "dark" ? "rgba(255, 255, 255, 0.1)" : "rgba(22, 119, 255, 0.1)" } },')
    cluster_ts = cluster_ts.replace('splitLine: { lineStyle: { color: "rgba(255, 255, 255, 0.05)" } }', 'splitLine: { lineStyle: { color: actualTheme === "dark" ? "rgba(255, 255, 255, 0.05)" : "rgba(22, 119, 255, 0.05)" } }')
    cluster_ts = cluster_ts.replace('shadowColor: "rgba(0, 229, 255, 0.5)", shadowBlur: 10', 'shadowColor: actualTheme === "dark" ? "rgba(0, 229, 255, 0.5)" : "rgba(22, 119, 255, 0.3)", shadowBlur: actualTheme === "dark" ? 10 : 6')
    cluster_ts = cluster_ts.replace('{ offset: 0, color: "rgba(0, 229, 255, 0.4)" }', '{ offset: 0, color: actualTheme === "dark" ? "rgba(0, 229, 255, 0.4)" : "rgba(22, 119, 255, 0.2)" }')
    cluster_ts = cluster_ts.replace('{ offset: 1, color: "rgba(0, 229, 255, 0.01)" }', '{ offset: 1, color: actualTheme === "dark" ? "rgba(0, 229, 255, 0.01)" : "rgba(22, 119, 255, 0.02)" }')
    with open(cluster_path, "w") as f:
        f.write(cluster_ts)

# Finally, docker restart
print("Restarting service...")
subprocess.run(["docker-compose", "down"], cwd="/opt/smartx-storage-forecast")
subprocess.run(["docker-compose", "up", "-d", "--build"], cwd="/opt/smartx-storage-forecast")
print("Done")
