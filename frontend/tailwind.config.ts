import type { Config } from "tailwindcss";

// The design tokens from the approved mockups: one ink, one indigo accent, amber for "in Toronto", green for good news.
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: { sans: ['"Inter Variable"', "system-ui", "sans-serif"] },
      colors: {
        canvas: "#F7F7F8",
        surface: "#FFFFFF",
        line: "#E4E4E8",
        "line-soft": "#F0F0F2",
        field: "#8A8F9C",
        ink: "#15161A",
        body: "#3A3D47",
        muted: "#5E6270",
        accent: { DEFAULT: "#4F46E5", hover: "#4338CA", ink: "#3730A3", tint: "#EEF0FF" },
        good: { DEFAULT: "#15622F", tint: "#E8F5EC" },
        warm: { DEFAULT: "#8A3B04", tint: "#FEF3E2" },
        bad: { DEFAULT: "#B42318", tint: "#FDECEA" },
        chip: "#F1F1F3",
      },
      borderRadius: { card: "14px" },
    },
  },
  plugins: [],
} satisfies Config;
