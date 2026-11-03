/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        background: "#0b0e14",
        surface: "#121721",
        border: "#232a38",
        brand: "#3b82f6",
        bullish: "#10b981",
        bearish: "#ef4444",
        neutral: "#f59e0b",
      }
    },
  },
  plugins: [],
}
