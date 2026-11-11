# Densemble

**Your AI team in Telegram — on the subscription you already pay for, with knowledge you own.**

```text
                          ▂┃▂      ·
                        ▂▆█┃█▆▂                   ·
                      ▂▆███┃███▆▂
                    ▂▆█████┃█████▆▂                   ·
                  ▁▆███████┃███████▆▁       ▂
        ·       ▁▅█████████┃█████████▅▁    ▅█▅
               ▄███████████┃███████████▄ ▃█████▃
          ▁▅▁▃█████████████┃████████████████████▅
         ▄█████            ┊            ██████████▂
       ▂▇██████   ▪   ▪    ┊    ▪   ▪   ███████████▄
      ▄████████   ╿   ╿    ┊    ╿   ╿   ███████████▪▆
    ▁▇█████████          ╺━━━╸
▂▂▂▃███████████           ╹ ╹                         ●
████████████████████████████████████████████████████████▆
```

Under the loud, busy world there is a hidden den: a hall inside the mountain, a round table,
niches for specialists, and a team of AI agents that works on your requests. You talk to them in
Telegram. The first one, **Glim**, is waiting at the door.

> **Experimental.** Free and open source (MIT). It works for its author every day, but there is
> no support yet and setup takes a while. Issues and ideas are welcome.

## What it is

- **A team, not one chatbot.** Agents with their own roles and characters, one Telegram bot each.
  Start with Glim, your personal assistant; add specialists when you need them.
- **Your subscription, not API bills.** Runs on your Claude (Pro/Max), GitHub Copilot
  or Cursor subscription through their official tools.
- **Knowledge you own.** Everything the agents know and write is plain Markdown in a folder on
  your computer. Claude Code, Copilot, Cursor and Codex read the same files, so you can leave
  any time and keep everything.
- **Private by design.** No web server, nothing exposed to the internet: Densemble only talks to
  Telegram and your AI provider. In Docker, the agents see only the folder you give them.
- **Voice, files and more.** Voice messages (recognised locally), documents and photos,
  reminders, shared workspaces for family or a small team.

## What you need

- A computer with **Docker** (macOS, Windows or Linux) that is on while you use the bots.
- **Telegram.**
- A **Claude Pro/Max**, **GitHub Copilot** or **Cursor** subscription.
- An AI coding agent to do the installation for you: **Claude Code**, **Copilot CLI** or **Codex**.

## Install

Let your AI agent do it. It follows [INSTALL.md](INSTALL.md) step by step and stops whenever it
needs you: to create a Telegram bot, to paste its token into a file, to log in in a browser.
Expect up to an hour the first time, most of it waiting for Docker. You need Docker installed and
running; everything else the agent does.

**Just the link.** Open Claude Code (or Copilot CLI, Codex) in any folder and say:

> Install Densemble from https://github.com/savavskoy/Densemble — clone it and follow its INSTALL.md.

**Or clone it yourself** and start the agent inside:

```sh
git clone https://github.com/savavskoy/Densemble.git
cd Densemble
claude        # or: copilot, codex
```

> Read INSTALL.md and install Densemble for me.

Either way you are letting an agent download code and run commands from it. Your agent will ask
before running commands; read [INSTALL.md](INSTALL.md) first if you want to know exactly what it
will do.

Prefer to do it by hand? Follow [platforms and Docker](docs/platforms.md). Running natively on
a Mac or Linux without Docker: [native setup](docs/native-setup.md).

## After installing

Write to your bot. Glim introduces himself, learns how to address you, shows you around and then
takes on whatever you ask. When one kind of work grows too big for one assistant, Glim suggests a
specialist and explains why.

Your workspace starts from one of the examples:

- [simple-workspace](examples/simple-workspace/README.md) — Glim and a profile for each person; the smallest start.
- [wiki-workspace](examples/wiki-workspace/README.md) — a knowledge base where material moves
  from raw sources through work in progress and proposals into a checked wiki.
- [wiki-split-workspace](examples/wiki-split-workspace/README.md) — the same wiki, with the agents
  in a separate Git repository, e.g. to share the knowledge but not the agents.

## Documentation

- [What Densemble does](docs/overview.md) and [how it is built](docs/concepts.md)
- [User guide](docs/user-guide/README.md)
- [Platforms and Docker](docs/platforms.md) · [native setup and operation](docs/native-setup.md)
- [Contracts](docs/contracts.md) — configuration schema and rules
- [SDK gate and acceptance](docs/acceptance.md) — what is verified and what is still open

## License

[MIT](LICENSE)
