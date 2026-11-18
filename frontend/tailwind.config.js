/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: ["Inter", "ui-sans-serif", "system-ui", "-apple-system", "Segoe UI", "Roboto", "sans-serif"],
        display: ["Iowan Old Style", "Palatino Linotype", "Book Antiqua", "Georgia", "serif"],
      },
      colors: { ink: "#0b0b0c", paper: "#fafaf9", line: "#e7e5e4" },
      keyframes: {
        rise: { from: { opacity: "0", transform: "translateY(6px)" }, to: { opacity: "1", transform: "none" } },
        pulseDot: { "0%, 80%, 100%": { opacity: "0.25" }, "40%": { opacity: "1" } },
      },
      animation: { rise: "rise 0.25s ease-out both", "pulse-dot": "pulseDot 1.2s infinite ease-in-out" },
    },
  },
  plugins: [],
};
