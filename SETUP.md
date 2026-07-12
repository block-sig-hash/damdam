# SETUP.md — From Zero to First Commit

This guide assumes you've never used a terminal, Git, or an AI coding
agent before. Every command is copy-paste-able. Where you need to
create an account or click through a website (not something a
terminal command can do for you), that's called out explicitly.

**Read this top to bottom once before starting** — the phases build
on each other, and Phase 5 (your first real task) only works if
Phases 1–4 are done correctly.

---

## Before you start: what everything is, in one paragraph each

- **WSL** — lets your Windows machine run a real Linux environment
  inside it. You already have this. Everything below happens *inside*
  WSL, not in a regular Windows terminal (PowerShell/CMD).
- **Git** — the tool that tracks every change to your code and docs.
- **GitHub** — the website that hosts your Git repository online, so
  you (and later, a co-founder or hires) can all see the same code.
- **Claude Code** — Anthropic's coding agent. Runs in your terminal,
  reads your project's instructions automatically, writes code, and
  reviews Codex's work.
- **Codex** — OpenAI's coding agent, included in your ChatGPT Plus
  plan. Runs in your terminal *or* can be assigned directly on
  GitHub. Does the bulk of the implementation work.
- **Docker** — lets you run the actual app (database, backend,
  background workers) on your own machine for testing, in exactly
  the same way it'll run in production.

---

## Phase 1: Prepare WSL

Open your WSL terminal (search "Ubuntu" or "WSL" in your Windows
Start menu, or open it from Windows Terminal).

**Before each step below, there's a "Check first" command.** Run
that first — if it prints back a version number or sensible output,
that piece is already installed and you can skip straight to the
next numbered step. If it says something like `command not found`,
proceed with the install command underneath it. Running an install
command again even when something's already installed generally
won't break anything, but checking first saves time and bandwidth.

**1.1 Update everything first:**

This one doesn't need a "check" — it's always safe to re-run, and
running it costs you a minute, not a redownload of things you
already have (it only fetches what's actually changed).
```bash
sudo apt update && sudo apt upgrade -y
```
This will ask for your WSL password (the one you set up when you
first installed WSL) — type it and press Enter. Nothing will appear
on screen as you type, that's normal.

**1.2 Install Git**

*Check first:*
```bash
git --version
```
If you see something like `git version 2.x.x`, Git is already
installed — skip to 1.3.

*If not installed:*
```bash
sudo apt install git -y
```

**1.3 Tell Git who you are**

*Check first:*
```bash
git config --global user.name
git config --global user.email
```
If both print back your actual name and email, this is already
done — skip to 1.4. If either comes back blank, set them (replace
with your actual name and the email you'll use for GitHub):
```bash
git config --global user.name "Ibrahim Adamu"
git config --global user.email "your-email@example.com"
```

**1.4 Install Node.js**

*Check first:*
```bash
command -v nvm && node --version
```
If this prints an `nvm` path followed by something like `v20.x.x`,
both nvm and Node 20 are already installed — skip to 1.5. If `nvm`
isn't found but you know Node is installed some other way, run
`node --version` alone — if it shows v20 or later, that's fine too,
though the nvm-based approach below is recommended since it makes
switching versions easier later if a specific tool needs one.

*If not installed:*
```bash
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.1/install.sh | bash
source ~/.bashrc
nvm install 20
nvm use 20
node --version
```
The last command should print something like `v20.x.x` — if it
does, this step worked.

**1.5 Install Python**

*Check first:*
```bash
python3.12 --version
```
If this prints `Python 3.12.x`, it's already installed — skip to
1.6.

*If not installed:*
```bash
sudo apt install python3.12 python3.12-venv python3-pip -y
python3 --version
```

**1.6 Install Docker Desktop**

*Check first*, inside your WSL terminal:
```bash
docker --version && docker info
```
If `docker --version` prints a version number **and** `docker info`
returns real output (not an error about not being able to connect),
Docker is already installed and the WSL integration is already
working — skip to 1.7. If `docker --version` works but `docker info`
errors out, Docker Desktop is installed but the WSL integration
toggle likely isn't on — jump to the toggle instructions below
without reinstalling anything.

*If not installed:* this one isn't a terminal command. Go to
[docker.com/products/docker-desktop](https://www.docker.com/products/docker-desktop/)
on Windows (not inside WSL), download and install Docker Desktop for
Windows. During setup, or afterward in Settings → Resources → WSL
Integration, **make sure the toggle for your WSL Ubuntu distro is
turned on**. This is the step people most often miss — without it,
Docker commands inside WSL won't work. Verify afterward with the
same check-first command above.

**1.7 Install GitHub CLI**

*Check first:*
```bash
gh --version
```
If this prints a version number, it's already installed — skip to
Phase 2.

*If not installed:*
```bash
type -p curl >/dev/null || sudo apt install curl -y
curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg | sudo dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg
sudo chmod go+r /usr/share/keyrings/githubcli-archive-keyring.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" | sudo tee /etc/apt/sources.list.d/github-cli.list > /dev/null
sudo apt update
sudo apt install gh -y
```

---

## Phase 2: Set Up GitHub

**2.1 If you don't already have a GitHub account**, create one at
[github.com](https://github.com) — use a professional email, since
this will eventually be a real company's account.

**2.2 Log in to GitHub from your terminal:**
```bash
gh auth login
```
Choose: `GitHub.com` → `HTTPS` → `Yes` (authenticate Git with your
GitHub credentials) → `Login with a web browser`. It'll show you a
code and open a browser page — paste the code there and click
Authorize. Once done, your terminal is now permanently connected to
your GitHub account; you won't need to log in again.

**2.3 Create the repository:**
```bash
gh repo create damdam --private --description "DamDam - Nigerian traveler connectivity platform"
```
This creates a **private** repository (only you and people you
invite can see it) named `damdam` under your GitHub account.

**2.4 Clone it to your machine and put the docs in it.** First,
navigate to wherever you want your projects to live (this example
uses your home folder — adjust if you prefer somewhere else):
```bash
cd ~
git clone https://github.com/YOUR-GITHUB-USERNAME/damdam.git
cd damdam
```

**2.5 Copy in the docs suite.** Take the `damdam-docs.zip` file
you've already downloaded from this conversation, and get it into
WSL. The easiest way: in Windows File Explorer, your WSL files are
accessible at `\\wsl$\Ubuntu\home\your-username\damdam` — drag the
unzipped contents of `damdam-docs` (the `docs` folder, `AGENTS.md`,
`CLAUDE.md`, `README.md`, `.github` folder) directly into that
`damdam` folder, replacing/merging as needed. Alternatively, if you
saved the zip to your WSL environment already, unzip it directly:
```bash
unzip ~/Downloads/damdam-docs.zip -d ~/damdam-temp
cp -r ~/damdam-temp/damdam-docs/* ~/damdam
cp -r ~/damdam-temp/damdam-docs/.github ~/damdam/
cp ~/damdam-temp/damdam-docs/AGENTS.md ~/damdam/
cp ~/damdam-temp/damdam-docs/CLAUDE.md ~/damdam/
```

**2.6 Push it to GitHub — this is your first real commit:**
```bash
cd ~/damdam
git add .
git commit -m "docs: initial spec suite"
git push origin main
```
Refresh your repository page on github.com — you should now see all
your docs there. This confirms the whole chain works: WSL → Git →
GitHub.

**2.7 Set up branch protection** (prevents anyone, including you,
from accidentally pushing broken code straight to `main`):
Go to your repo on github.com → Settings → Branches → Add branch
protection rule → type `main` → check "Require a pull request before
merging" → Save.

**2.8 Create the `develop` branch** (per your repo's own branch
strategy in `README.md`):
```bash
git checkout -b develop
git push origin develop
```

---

## Phase 3: Set Up Claude Code

**3.1 Create an Anthropic account and API key.** Go to
[console.anthropic.com](https://console.anthropic.com), sign up, add
a payment method (Settings → Billing), then go to API Keys → Create
Key. **Copy the key immediately and save it somewhere safe** — you
won't be able to see it again after you navigate away.

**3.2 Set a spend limit** while you're in the console (Settings →
Limits) — a safety net so a runaway session can't surprise you with
a large bill, per the cost-optimization guidance already in your
`AGENTS.md`.

**3.3 Save your API key in WSL** so Claude Code can use it
automatically every time, without you re-entering it:
```bash
echo 'export ANTHROPIC_API_KEY="paste-your-key-here"' >> ~/.bashrc
source ~/.bashrc
```

**3.4 Install Claude Code**

*Check first:*
```bash
claude --version
```
If this prints a version number, it's already installed — skip to
3.5.

*If not installed:*
```bash
npm install -g @anthropic-ai/claude-code
```

**3.5 Verify it works.** Navigate into your repo and start it:
```bash
cd ~/damdam
claude
```
If this opens an interactive Claude Code session without asking you
to log in (since you're using the API key), it worked. Type
`/exit` to leave for now.

---

## Phase 4: Set Up Codex

**4.1 Install Codex CLI**

*Check first:*
```bash
codex --version
```
If this prints a version number, it's already installed — skip to
4.2.

*If not installed:*
```bash
npm install -g @openai/codex
```

**4.2 Sign in with your ChatGPT account** (this uses your existing
Plus plan, no separate API billing):
```bash
codex
```
On first run, it'll prompt you to sign in — choose "Sign in with
ChatGPT" and follow the browser prompt, same pattern as the GitHub
login above.

**4.3 Verify it works:**
```bash
cd ~/damdam
codex
```
It should start an interactive session. Type `exit` or press
`Ctrl+C` to leave for now.

**4.4 Connect Codex to GitHub for the `@codex`-on-issues workflow.**
Go to [chatgpt.com/codex](https://chatgpt.com/codex) in your browser
(not the terminal), find the settings for connecting a GitHub
repository/environment, and connect it to your `damdam` repo. This
is what lets you later tag `@codex` on a GitHub Issue and have it
pick up the work without you running anything locally.

---

## Phase 5: Your First Real Task

Don't jump straight into building screens — per `AGENTS.md`, the
mobile app can't start until `docs/design-system.md` (currently a
placeholder) is actually produced. This is the perfect first task:
it's exactly what Claude Code should do (not Codex), it's
low-risk to get wrong (easy to review, easy to redo), and it proves
your whole setup works end to end.

**5.1 Start Claude Code in your repo:**
```bash
cd ~/damdam
claude
```

**5.2 Give it the task** (type this into the Claude Code session):
```
Read docs/design-system.md, docs/frontend-mobile.md, and docs/prd.md
section 3.1. Produce the full design system per the required
sections listed in docs/design-system.md — color tokens, typography
scale, spacing scale, component patterns, iconography, motion
conventions, and platform adaptation rules. Use the awesome-design-md
references (Wise, Expo, Coinbase) mentioned in that file as
inspiration only, not templates to copy. Update
docs/design-system.md directly with real values, and remove the
"SCAFFOLD, NOT YET PRODUCED" status note once complete.
```

**5.3 Review what it produces.** Claude Code will show you its
proposed changes before applying them (or ask permission at each
step, depending on your settings) — read through it, ask follow-up
questions if something looks off, and only accept once you're happy.

**5.4 Commit and push:**
```bash
git add docs/design-system.md
git commit -m "docs: produce initial design system"
git push origin main
```

---

## Phase 6: The Ongoing Workflow

Once Phase 5 is done, here's the actual day-to-day pattern:

**6.1 Turn a user story into a GitHub Issue.** Go to your repo on
github.com → Issues → New Issue → choose the "Feature" template →
fill in the `US-XX` ID and acceptance criteria copied from
`docs/prd.md`.

**6.2 Hand it to Codex — two ways:**
- **Remote/autonomous:** on the Issue itself, type a comment tagging
  `@codex` with the task. It'll work in the cloud and open a Pull
  Request when done — you don't need a terminal open.
- **Local/interactive** (better while you're still learning the
  system and want to watch it work): open a terminal, run `codex`,
  and say "implement the feature described in Issue #3."

**6.3 Review with Claude Code.** Once Codex opens a Pull Request, in
a **second terminal window**, run `claude` and say: "Review Pull
Request #[number] against its linked user story's acceptance
criteria in docs/prd.md." This is the "two terminals running
simultaneously" you asked about — one isn't blocked by the other,
but they're working on different things in sequence (Codex builds,
then Claude reviews what Codex built), not literally the same task
at the same moment.

**6.4 Merge once Claude approves and CI passes.** On the Pull
Request page on github.com, click "Merge" once you see a green
checkmark from the automated tests and Claude's review comment
looks satisfied.

**6.5 Running the app locally to actually see it:**
```bash
cd ~/damdam
docker compose up
```
This starts the full backend stack (API, database, background
workers) on your machine, matching `docs/infrastructure.md` §11.3.

---

## Troubleshooting

- **`docker: command not found` inside WSL** → Docker Desktop's WSL
  integration toggle (Phase 1.6) isn't turned on. Open Docker
  Desktop on Windows, check Settings → Resources → WSL Integration.
- **`claude` or `codex` command not found** → close and reopen your
  WSL terminal (this reloads your PATH after the npm install), or
  run `source ~/.bashrc`.
- **Git asks for a username/password when pushing** → run
  `gh auth login` again (Phase 2.2); this shouldn't happen if that
  step completed correctly.
- **Claude Code says it can't find an API key** → check
  `echo $ANTHROPIC_API_KEY` in your terminal — if nothing prints,
  redo Phase 3.3 and make sure you ran `source ~/.bashrc` afterward.
