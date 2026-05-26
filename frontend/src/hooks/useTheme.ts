import { useEffect, useState } from "react";
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
