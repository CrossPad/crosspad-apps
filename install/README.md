# Install the CrossPad tools

This puts everything your computer needs to update your CrossPad on it, and
opens **CP Tools** — the program that updates the CrossPad and chooses its apps.

**You need:**

- a Windows, Mac or Linux computer with about **10 GB free**
- the **USB-C cable** of your CrossPad
- a **GitHub account** that has access to CrossPad (ask on the CrossPad Discord
  with your GitHub user name if you don't have access yet)
- **30 minutes** the first time (mostly waiting for downloads)

You type one line. Everything else happens by itself.

---

## Windows

### 1. Open PowerShell

Click **Start**, type `powershell`, and click **Windows PowerShell**.

![Start menu with "powershell" typed in the search box](img/win-1-start.png)

### 2. Paste the install line

Copy this line, click into the blue/black PowerShell window, **right-click** to
paste, and press **Enter**:

```powershell
powershell -ExecutionPolicy Bypass -c "irm https://raw.githubusercontent.com/CrossPad/crosspad-apps/main/install/install.ps1 | iex"
```

![The install line pasted into PowerShell](img/win-2-paste.png)

### 3. Sign in to GitHub (once)

Early on (step 2) the installer shows a **one-time code** — it is already
copied for you. Press **Enter**: your browser opens GitHub. Sign in if it asks,
press **Ctrl+V** to paste the code, and click **Continue**, then
**Authorize**. Come back to the PowerShell window — it carries on by itself.
Next time it remembers you.

![The one-time code, copied, and "Press Enter to open github.com/login/device"](img/win-4-code.png)

### 4. Wait while the steps tick by

The installer works through 10 steps. Each one ends with a green **[OK]**. The
longest is step 4, ESP-IDF — about 15 minutes. It also installs **VS Code**
(with the ESP-IDF extension and the CP Tools buttons) and **Node.js** with the
CrossPad tools for AI assistants, and checks at the end that `git`, `python`,
`gh`, `code`, `node` and `cptools` all work in a new terminal. You can leave
the window alone.

![Steps 1 and 2 finished with [OK], step 3 working](img/win-3-steps.png)

### 5. "All set"

The installer checks everything once more and prints **All set**, then opens
CP Tools. A line that says *No CrossPad found* only means the board is not
plugged in yet.

![The final check and "All set."](img/win-5-done.png)

### 6. Open CP Tools

From now on, open **CP Tools** from the shortcut on your desktop.

![The CP Tools shortcut on the desktop](img/win-6-shortcut.png)

---

## Mac and Linux

1. Open **Terminal** (Mac: press ⌘ Space, type `terminal`, Enter).
2. Paste this line and press **Enter**:

   ```bash
   curl -fsSL https://raw.githubusercontent.com/CrossPad/crosspad-apps/main/install/install.sh | bash
   ```

3. Type your computer password when asked (it installs a few system tools).
   On a Mac, if a window asks to install the *Command Line Tools*, click
   **Install**, wait, then paste the line again.
4. Sign in to GitHub when the code appears (same as step 3 above).
5. Wait for **All set**. It looks like this:

   ```
   Step 4 of 8: ESP-IDF v5.5.5
     the compiler for the CrossPad's chip — about 10 minutes the first time
     ✓ ESP-IDF v5.5.5

   Step 5 of 8: USB access
     so the tools can talk to the board
     ✓ added — log out and back in once for it to take effect
   …
   All set. Next time, open CP Tools with:  /home/you/CrossPad/cptools
   Plug your CrossPad in with a USB cable before [1] Update my CrossPad.
   ```

6. From now on, open CP Tools with `~/CrossPad/cptools`.

On Linux, **log out and back in once** after the first install, so your user
may talk to USB devices.

---

## The first time in CP Tools

CP Tools greets you once and explains its four keys:

![The CP Tools welcome screen](img/cp-1-welcome.png)

Then the first screen. **The top line always tells you what to do next.**
Plug your CrossPad in and press **1** to put the newest version on it.

![The CP Tools first screen](img/cp-2-dashboard.png)

- **1** Update my CrossPad — downloads, builds and puts it on the board
- **2** Add or remove apps
- **3** Something's wrong — every check, with what to do about it
- **?** help on any screen · **q** back

---

## If something goes wrong

- **Run the install line again.** It only redoes what is missing or broken,
  and never overwrites your own changes.
- In CP Tools press **3** (*Something's wrong*). Every red line says what to do.
- Still stuck? In *Something's wrong* press **s**. It saves one file with
  everything a helper needs (no passwords). Send it on the CrossPad Discord,
  channel **#support**, with one line about what you were doing.

![Something's wrong, with a fix under each problem](img/cp-3-wrong.png)

<details>
<summary>Options for people who know what they are doing</summary>

Set these before running the install line:

| Variable | Default | What |
|---|---|---|
| `CROSSPAD_DIR` | `C:\CrossPad`, `~/CrossPad` | where the project goes (no spaces) |
| `CROSSPAD_BRANCH` | `crosspad_v20` | branch of CrossPad/platform-idf |
| `CROSSPAD_IDF_DIR` | `C:\esp\esp-idf`, `~/esp/esp-idf` | where ESP-IDF goes |
| `CROSSPAD_YES=1` | | answer yes to every question |
| `CROSSPAD_NO_HIL=1`, `CROSSPAD_NO_VSCODE=1`, `CROSSPAD_NO_MCP=1`, `CROSSPAD_NO_TUI=1` | | skip the test tools, VS Code, the AI-assistant tools, or opening CP Tools at the end |

Windows installs everything for your user only (no administrator needed) and
keeps to short folders, because ESP-IDF cannot build in paths with spaces or
non-English letters.
</details>
