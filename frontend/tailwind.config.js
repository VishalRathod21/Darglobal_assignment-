/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: ["'Plus Jakarta Sans'", "Inter", "system-ui", "sans-serif"],
        display: ["'Outfit'", "'Plus Jakarta Sans'", "system-ui", "sans-serif"],
      },
      colors: {
        ink: "#0b0f19",
        paper: "#f8fafc",
        line: "#e2e8f0",
        gold: {
          50: "#fbf8f3",
          100: "#f5eee2",
          200: "#e9dac2",
          300: "#dbbf98",
          400: "#cda06d",
          500: "#c1884d",
          600: "#b0723f",
          700: "#925934",
          800: "#77482f",
          900: "#623d29",
        },
        brand: {
          dar: "#b45309",
          wasalt: "#059669",
        },
      },
      keyframes: {
        rise: { from: { opacity: "0", transform: "translateY(8px)" }, to: { opacity: "1", transform: "none" } },
        pulseDot: { "0%, 80%, 100%": { opacity: "0.2" }, "40%": { opacity: "1" } },
        shimmer: { "0%": { backgroundPosition: "-200% 0" }, "100%": { backgroundPosition: "200% 0" } },
      },
      animation: {
        rise: "rise 0.3s cubic-bezier(0.16, 1, 0.3, 1) both",
        "pulse-dot": "pulseDot 1.4s infinite ease-in-out",
        shimmer: "shimmer 2s infinite linear",
      },
    },
  },
  plugins: [],
};
