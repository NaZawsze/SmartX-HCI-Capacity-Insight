import re

# Update TrendChart.tsx
trend_path = "/opt/smartx-storage-forecast/frontend/src/components/TrendChart.tsx"
with open(trend_path, "r") as f:
    trend_ts = f.read()

if "actualTheme" not in trend_ts:
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
    print("Updated TrendChart.tsx")

# Update ClusterCapacityChart.tsx
cluster_path = "/opt/smartx-storage-forecast/frontend/src/components/ClusterCapacityChart.tsx"
with open(cluster_path, "r") as f:
    cluster_ts = f.read()

if "actualTheme" not in cluster_ts:
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
    print("Updated ClusterCapacityChart.tsx")

print("Charts theme patches applied!")
