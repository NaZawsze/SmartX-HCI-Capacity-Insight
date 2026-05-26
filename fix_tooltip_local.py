import re

with open("remote_TrendChart.tsx", "r") as f:
    code = f.read()

# Revert my bad Python escaping mistake if it exists, or just do the correct replace from original
code = code.replace(
    r"<strong style=\"color:${actualTheme === \'dark\' ? \'#00e5ff\' : \'#1677ff\'}\">${formatBytes(item.value)}</strong>",
    '<strong style="color:${actualTheme === \'dark\' ? \'#00e5ff\' : \'#1677ff\'}">${formatBytes(item.value)}</strong>'
)

# And if it is still the original:
code = code.replace(
    '<strong style="color:#00e5ff">${formatBytes(item.value)}</strong>',
    '<strong style="color:${actualTheme === \'dark\' ? \'#00e5ff\' : \'#1677ff\'}">${formatBytes(item.value)}</strong>'
)

with open("remote_TrendChart.tsx", "w") as f:
    f.write(code)

print("Fixed locally")
