#!/usr/bin/env node
// Prints the Densemble den: a hidden hall inside a hillside by the sea, with Glim at the open door.
// Plain text with --plain, NO_COLOR or a non-terminal output; colours in a terminal (FORCE_COLOR forces them).
// No dependencies, so it runs before `npm ci`.

const art = String.raw`
      ·                                     ·
               *                                          *
                          ▂┃▂      ·
                        ▂▆█┃█▆▂                   ·
   ·                  ▂▆███┃███▆▂
                    ▂▆█████┃█████▆▂                   ·
                  ▁▆███████┃███████▆▁       ▂               ·
        ·       ▁▅█████████┃█████████▅▁    ▅█▅
               ▄███████████┃███████████▄ ▃█████▃
          ▁▅▁▃█████████████┃████████████████████▅
         ▄█████            ┊            ██████████▂
       ▂▇██████   ▪   ▪    ┊    ▪   ▪   ███████████▄
      ▄████████   ╿   ╿    ┊    ╿   ╿   ███████████▪▆
    ▁▇█████████          ╺━━━╸
▂▂▂▃███████████           ╹ ╹                         ●
████████████████████████████████████████████████████████▆
▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀

  ~   ~~     ~    ~~~   ~      ~~    ~     ~~~    ~   ~~      ~
`.slice(1);
const title = "                    D  E  N  S  E  M  B  L  E";
const tagline = "          your hidden den · the team is already inside";

// [truecolor, 256-colour fallback] per glyph group, from the Densemble palette.
const palette = {
  stone: ["94;110;118", 66],
  beam: ["201;154;85", 179],
  lamp: ["229;172;89", 179],
  dot: ["255;196;107", 215],
  paper: ["233;226;212", 254],
  sea: ["79;127;143", 66],
  star: ["233;226;212", 250],
};
const groups = [
  ["█▁▂▃▄▅▆▇▀", "stone"], ["┃┊", "beam"], ["▪", "lamp"], ["●", "glim"],
  ["━╺╸╹╿", "paper"], ["~", "sea"], ["·*", "star"],
];
const glyph = new Map(groups.flatMap(([chars, name]) => [...chars].map((char) => [char, name])));

const args = process.argv.slice(2);
const color = !args.includes("--plain") && !process.env.NO_COLOR &&
  (Boolean(process.env.FORCE_COLOR) || Boolean(process.stdout.isTTY));
const truecolor = /truecolor|24bit/i.test(process.env.COLORTERM ?? "");

function paint(text, name, bold = false) {
  if (!color) return text;
  const [rgb, ansi] = palette[name];
  const code = truecolor ? `38;2;${rgb}` : `38;5;${ansi}`;
  return `\x1b[${bold ? "1;" : ""}${code}${name === "star" ? ";2" : ""}m${text}\x1b[0m`;
}

const scene = art.split("\n").map((line) =>
  [...line].map((char) => (glyph.has(char) ? paint(char, glyph.get(char), char === "●") : char)).join(""));
process.stdout.write(["", ...scene, "", paint(title, "lamp", true), paint(tagline, "paper"), ""].join("\n") + "\n");
