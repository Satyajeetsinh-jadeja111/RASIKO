/** Vijay Navagraha theme. Light only; no black, grey or blue anywhere. */
module.exports = {
  content: ["../templates/**/*.html", "../apps/**/templates/**/*.html", "../static/js/**/*.js", "../apps/**/*.py"],
  darkMode: "class", // never toggled: the site is light-only
  theme: {
    colors: {
      transparent: "transparent",
      current: "currentColor",
      white: "#FFFFFF",
      kesari: "#FB8C00",
      kumkum: "#E53935",
      sindoor: "#B71C2C",
      maroon: "#7A1F2B",
      tulsi: { DEFAULT: "#2FA05A", deep: "#1B6E42", light: "#EAF7EE" },
      haldi: { DEFAULT: "#F4B400", deep: "#8A5A00", light: "#FFE9A8" },
      chandan: "#FFF4E0",
      kamal: "#FDE7E4",
      mitti: "#F3E2C3",
      kajal: { DEFAULT: "#3E2723", soft: "#6D4C41" },
      line: "#F3E3CC",
    },
    fontFamily: {
      head: ["Fredoka", "Baloo Shubh", "ui-rounded", "system-ui", "sans-serif"],
      body: ["Nunito Sans", "Baloo Shubh", "system-ui", "sans-serif"],
    },
    extend: {
      borderRadius: { card: "20px", xl2: "22px" },
      boxShadow: {
        card: "0 6px 22px rgba(122,31,43,.06), 0 1px 3px rgba(122,31,43,.05)",
        lift: "0 14px 34px rgba(122,31,43,.12), 0 2px 6px rgba(122,31,43,.06)",
        glow: "0 8px 20px rgba(47,160,90,.32)",
      },
      backgroundImage: {
        sunrise: "linear-gradient(90deg,#E53935,#FB8C00 55%,#F4B400)",
      },
    },
  },
  plugins: [],
};
