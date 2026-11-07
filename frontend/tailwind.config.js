/** ScoutIQ tokens: a chalk tactics board on a felt-green working surface. */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        board: { DEFAULT: "#22343C", deep: "#1A2A31", line: "#3A5059" },
        chalk: { DEFAULT: "#EEF2EF", dim: "#B9C6C4" },
        surface: { DEFAULT: "#E4EAE6", raised: "#FFFFFF", sunk: "#D8E0DB" },
        ink: { DEFAULT: "#1C2A30", soft: "#4C5D63", faint: "#55656A" },
        marker: { DEFAULT: "#F2C230", ink: "#7A5C00" },
        signal: { DEFAULT: "#B5452F", soft: "#F6E3DE" },
        rule: "#CAD4CF",
      },
      fontFamily: { sans: ['"Archivo"', "system-ui", "sans-serif"] },
      maxWidth: { prose: "68ch" },
    },
  },
  plugins: [],
};
