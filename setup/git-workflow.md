# Git Workflow -- How to Save and Submit Your Work

Git is how your code gets saved and submitted. Think of it like Google Drive for code -- but instead of auto-saving, you choose when to save (called "committing") and when to upload (called "pushing").

## The Flow

```
Your computer          GitHub (cloud)           Lodewijk sees it
     |                      |                        |
  [edit files]              |                        |
     |                      |                        |
  [commit] ----push----> [your branch]               |
     |                      |                        |
     |                   [open PR] ------review----> [main branch]
```

**Commit** = save a snapshot of your work locally
**Push** = upload that snapshot to GitHub
**Pull Request (PR)** = ask to merge your work into the main project (this is your submission)

---

## First-Time Setup

You only do this once. Claude Code can run these commands for you -- just ask.

### Step 1: Check if Git is installed
```bash
git --version
```
If you see a version number, you are good. If not, ask Thanh to help install it.

### Step 2: Set your name and email
```bash
git config --global user.name "YOUR FULL NAME"
git config --global user.email "YOUR EMAIL"
```

### Step 3: Authenticate with GitHub
```bash
gh auth login
```
Follow the prompts. Choose "GitHub.com", "HTTPS", and "Login with a web browser". It will give you a code to paste into your browser.

If `gh` is not installed, ask Thanh.

### Step 4: Clone the repo
```bash
cd ~
git clone https://github.com/MSPLaunchpadLabs/level-up.git launchpad-labs
cd launchpad-labs
```

### Step 5: Create your working branch
```bash
git checkout -b YOUR-NAME/main
git push -u origin YOUR-NAME/main
```

Replace `YOUR-NAME` with your actual first name (lowercase, no spaces). Example: `ayesha/main`

---

## Your 4 Daily Commands

These are the only git commands you will use day to day. Claude Code can run them for you.

### 1. Check what changed
```bash
git status
```
Shows which files you have changed since your last commit. Green = staged (ready to commit). Red = changed but not staged.

### 2. Stage your changes
```bash
git add .
```
This tells git "I want to save all my changes." The `.` means "everything in this folder."

If you want to be selective (recommended):
```bash
git add bounty/PROGRESS.md
git add src/my-new-file.js
```

### 3. Commit (save a snapshot)
```bash
git commit -m "add: description of what you built"
```

Good commit messages:
- `"add: keyword research accelerator v1"`
- `"fix: handle empty API response in QA scanner"`
- `"update: improve prompt for meta tag generation"`

Bad commit messages:
- `"stuff"`
- `"changes"`
- `"asdfg"`

### 4. Push (upload to GitHub)
```bash
git push
```

If this is your first push on a new branch:
```bash
git push -u origin YOUR-NAME/feature-name
```

---

## How to Submit Your Bounty (Open a Pull Request)

When your bounty is ready for review:

### Option A: Let Claude do it
Ask Claude: "Open a pull request to main with a summary of what I built."

### Option B: Do it yourself
```bash
gh pr create --title "Bounty #XX: Your Bounty Name" --body "Summary of what was built and how to test it"
```

### Option C: Use the GitHub website
1. Go to https://github.com/MSPLaunchpadLabs/level-up
2. Click "Pull requests" tab
3. Click "New pull request"
4. Set base = `main`, compare = `your-name/branch-name`
5. Add a title and description
6. Click "Create pull request"

Thanh reviews all PRs. He will leave comments if anything needs fixing.

---

## Branch Naming

Always use this format: `your-name/what-you-are-building`

Examples:
- `ayesha/gbp-post-generator`
- `jesse/webflow-qa-skill`
- `erman/design-brief-autogen`
- `silvana/client-milestone-notifier`

---

## Common Problems and Fixes

### "fatal: not a git repository"
You are not inside the project folder. Run:
```bash
cd ~/launchpad-labs
```

### "error: failed to push some refs"
Someone else pushed changes to your branch (unlikely) or you need to pull first:
```bash
git pull origin YOUR-BRANCH-NAME
```
Then try `git push` again.

### "nothing to commit, working tree clean"
You have not changed anything since your last commit. This is fine -- it means everything is saved.

### "Your branch is ahead of origin by X commits"
You have commits that have not been pushed yet. Run:
```bash
git push
```

### "Please commit or stash your changes before switching branches"
You have unsaved changes. Commit them first:
```bash
git add .
git commit -m "save: work in progress"
```

### Authentication failed
Run `gh auth login` again and follow the prompts.

### Merge conflict
This means two people changed the same file. Ask Thanh or your build buddy for help. Do not try to resolve it yourself if you are not comfortable with git.

### "Pre-commit hook failed: secrets detected"
The safety hook found something that looks like an API key in your code. This is a GOOD thing -- it prevented you from accidentally publishing a secret.
1. Check which file triggered it (the error message will say)
2. Move the secret to your `.env` file instead
3. Reference it in code as `process.env.YOUR_KEY_NAME`
4. Try committing again