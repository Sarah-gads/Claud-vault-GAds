# Getting Unstuck -- Self-Service Troubleshooting

Before pinging Thanh, check this file. It covers the most common problems with exact steps to fix them. Thanh updates this file throughout the event as new issues come up -- pull the latest version with `git pull origin main` if your copy feels outdated.

---

## 1. "I need an API key that is not in my .env file"

**Symptom:** Claude says it cannot find a key, or you see an empty variable in your `.env`.

**Fix:**
1. Open `setup/credentials.md` and check if the service is listed
2. If it is listed as GREEN, the key should be in your `.env` -- check for typos or empty values
3. If it is listed as YELLOW, request it from Thanh in `#level-up`: "Hi Thanh, I need [SERVICE] for bounty #[NUMBER]"
4. If it is listed as ORANGE, Thanh will check with Lodewijk before approving
5. If it is listed as RED, you cannot have it. Ask Thanh for a sandbox alternative

**Response time:** Thanh responds to key requests within 2 hours during event hours.

---

## 2. "My API key is not working"

**Symptom:** You get "401 Unauthorized", "403 Forbidden", or "Invalid API key" errors.

**Diagnosis checklist:**
1. **Is the .env loaded?** Restart your Claude Code session (type `/clear` and start a new conversation). Claude Code reads `.env` at session start.
2. **Is the key correct?** Open `.env` and look at the value. Keys should not have quotes around them, no trailing spaces, and no line breaks inside the value.
3. **Is it the right key for the service?** Supabase has separate `ANON_KEY` and `SERVICE_KEY`. Stripe has `sk_test_` vs `sk_live_`. Make sure you are using the correct one.
4. **Is the service rate-limited?** Some APIs have limits per minute. Wait 60 seconds and try again.
5. **Has the key expired?** Some keys (OAuth tokens, session cookies) expire. Ask Thanh for a fresh one.

**Still broken?** Post in `#level-up`: "@Thanh API key for [SERVICE] is returning [EXACT ERROR MESSAGE]"

---

## 3. "I do not know how to commit to GitHub"

**Symptom:** You have built something and want to save it, but git feels confusing.

**Quick fix -- ask Claude:**
> "Commit all my changes with the message 'add: [describe what you built]' and push to GitHub"

Claude will run the commands for you and explain what each one does.

**If you want to do it yourself:**
```bash
git add .
git commit -m "add: description of what you built"
git push
```

**Full guide:** Read `setup/git-workflow.md` for the complete walkthrough.

---

## 4. "Claude keeps going in the wrong direction"

**Symptom:** Claude is building something you did not ask for, or it keeps making the same mistake.

**Fix:**
1. Type `/clear` in Claude Code. This resets the conversation and lets you start fresh.
2. Start the new conversation with a clear, specific prompt. Bad: "Fix it." Good: "The keyword extraction function in src/keywords.js returns an empty array when the SEMrush API returns more than 100 results. Fix the pagination logic."
3. If Claude keeps misunderstanding your bounty, paste the contents of `bounty/BOUNTY.md` into the conversation as context.

**Pro tip:** When starting a new session, paste this at the top:
> "Read bounty/PROGRESS.md to see what we did last time, then read bounty/BOUNTY.md for the full bounty brief."

---

## 5. "My Claude Code session crashed or I lost my work"

**Symptom:** Claude Code closed unexpectedly, your terminal froze, or you lost track of what was done.

**Fix:**
1. Open a new Claude Code session
2. Ask: "Read bounty/PROGRESS.md and tell me where we left off"
3. If PROGRESS.md is empty or missing, check `git log --oneline -10` to see your recent commits
4. If git has no commits, check for any files you created: `ls -la src/` or `ls -la bounty/`
5. Resume from wherever the trail picks up

**Prevention:** Commit your work frequently. Every 30-60 minutes, or whenever something is working:
```bash
git add .
git commit -m "save: work in progress"
git push
```

---

## 6. "I want to deploy my project for testing or Demo Day"

**Symptom:** You have a working build and want a live URL.

**Fix:**
All deployments go through Thanh. This is intentional -- it prevents accidentally deploying to a production URL.

**Steps:**
1. Make sure all your code is committed and pushed to GitHub
2. Post in `#level-up`: "@Thanh I am ready to deploy bounty #[NUMBER]. Here is what it does: [ONE SENTENCE]. Environment variables it needs: [LIST THEM]."
3. Thanh deploys to a preview URL on Vercel (not production)
4. You get a URL like `bounty-07-webflow-qa.vercel.app` for testing and Demo Day

**Response time:** Thanh handles deploy requests within 4 hours.

---

## 7. "I think my bounty is already built or overlaps with someone else's"

**Symptom:** You found existing code or another participant working on something similar.

**Fix:**
1. Search the shared repo: `ls MSPLaunchpadLabs/level-up/shared/`
2. Check the `bounty/BOUNTY.md` file -- the "Related Bounties" section lists connections
3. Ask Thanh in `#level-up`: "Is bounty #[X] already built? I found [WHAT YOU FOUND]."

Do NOT start from scratch if something already exists. Build on top of it or extend it. Thanh will clarify ownership.

---

## 8. "I want to add a feature outside my bounty scope"

**Symptom:** While building, you thought of something useful that your bounty brief does not mention.

**Fix:**
1. Finish your current bounty deliverable first -- scope creep is the #1 risk
2. Once your bounty meets "Shipped + Proven", propose the addition in `#level-up`
3. Format: "Bounty #[X] extra: [WHAT YOU WANT TO ADD]. It would [VALUE]. Takes ~[TIME ESTIMATE]."
4. Lodewijk decides within 1 day. If approved, it becomes a bonus task worth extra credit.

---

## 9. "I need a paid tool or API that is not set up"

**Symptom:** Your bounty references a tool (Frase, Canva, Gamma, etc.) that is not in your `.env`.

**Fix:**
1. Check `setup/credentials.md` to confirm it is not already available
2. Post in `#level-up`: "@Thanh I need [TOOL] for bounty #[NUMBER]. It costs [AMOUNT/month]. I need it because [REASON]."
3. Thanh confirms the need and checks if a free alternative exists
4. Lodewijk approves the spend
5. Thanh sets up the tool and adds the key to your `.env`

**Budget rule:** Each participant has a no-ask tool budget of EUR 50-100. Above that requires Lodewijk's explicit approval.

---

## 10. "Supabase gives me a permission error"

**Symptom:** You see "permission denied", "RLS policy violation", or "new row violates row-level security policy" errors.

**Fix:**
1. Confirm you are using the `level-up-sandbox` project (check your `SUPABASE_URL` in `.env`)
2. If you just created a new table, RLS might be enabled but you have not added a policy yet. Ask Claude: "Add an RLS policy to my [TABLE] table that allows all operations for authenticated users"
3. If you are trying to access a table someone else created, check if they set RLS policies that restrict access. Coordinate with your build buddy.

**If you see a different Supabase URL:** STOP. You may be accidentally connecting to a production database. Post in `#level-up` with `@Thanh` immediately.

---

## 11. "Git pre-commit hook rejected my commit (secrets detected)"

**Symptom:** You try to commit and get an error about "secrets detected" or "gitleaks found issues."

**This is working correctly.** The hook prevented you from accidentally pushing a secret to GitHub.

**Fix:**
1. Read the error message -- it tells you which file and which line has the secret
2. Move the secret value to your `.env` file
3. In your code, replace the hardcoded value with `process.env.YOUR_KEY_NAME` (JavaScript) or `os.environ['YOUR_KEY_NAME']` (Python)
4. Run `git add .` and try committing again
5. If the hook still blocks and you believe it is a false positive, post in `#level-up` with `@Thanh`

**Do NOT bypass the hook.** If you are tempted to use `--no-verify`, stop. Ask Thanh instead.

---

## 12. "I cannot install a package or dependency"

**Symptom:** `npm install`, `pip install`, or another package manager fails.

**Fix:**
1. Make sure you are in your workspace folder: `cd ~/launchpad-labs`
2. For npm: `npm install package-name`
3. For Python: `pip install package-name` or `pip3 install package-name`
4. If you get permission errors on Windows, try running your terminal as Administrator
5. If you get network errors, check your internet connection

**If a system-level tool is needed** (like ffmpeg, gitleaks, or a global CLI): ask Thanh. He handles system-level installs.

---

## 13. "Claude says it does not have access to a tool or MCP"

**Symptom:** Claude says "I don't have access to [SERVICE]" even though you think you should.

**Fix:**
1. Check `setup/credentials.md` -- is the key in your `.env`?
2. If yes, restart your Claude Code session (`/clear` and start fresh)
3. If no, request the key from Thanh
4. Some MCPs (Playwright, shadcn-ui, UX Best Practices) need to be configured in Claude Code's settings file. Ask Thanh if you think an MCP should be available.

**Common MCP tools that work out of the box:** Playwright (browser automation), shadcn-ui (React components), UX Best Practices (design review).

---

## 14. "I am stuck and nothing in this file helps"

**Symptom:** You have tried everything above and you are still blocked.

**Escalation path:**

| Step | Who | How | Response Time |
|------|-----|-----|---------------|
| 1 | Your build buddy | DM them on Discord | Minutes (if online) |
| 2 | Thanh | Post in `#level-up` with `@Thanh` | Within 2 hours |
| 3 | Lodewijk | Post in `#level-up` with `@Lodewijk` | Same day |

**What to include in your message:**
- Your bounty number
- What you were trying to do
- The exact error message (screenshot or copy-paste)
- What you already tried from this file

Good: "@Thanh Bounty #29 -- GBP Post Generator. Trying to authenticate with Google Business Profile API. Getting 'OAuth scope not authorized' error. Already checked .env, key is present, restarted Claude Code."

Bad: "@Thanh it does not work"

---

## 15. "I am not sure where to start on my bounty"

**Symptom:** You have read `bounty/BOUNTY.md` but feel overwhelmed.

**Fix:**
1. Ask Claude: "Read bounty/BOUNTY.md and break it down into small steps I can do one at a time"
2. Start with the smallest possible thing that works. Not the full bounty -- just one tiny piece.
3. Examples of good first steps:
   - SEO bounty: "Generate one set of meta tags for one page of one client"
   - Design bounty: "Extract brand colors from one client URL using OpenBrand"
   - Email bounty: "Write one email template for one milestone notification"
   - QA bounty: "Run one accessibility check on one page"
4. Once that tiny thing works, expand it to handle more cases
5. When you have 3 working cases, you are probably close to "Shipped + Proven"

**The 20-minute rule:** If you have been stuck for 20 minutes without making progress, stop struggling alone. Message your build buddy or post in `#level-up`. The event is 3 weeks -- every hour of frustration is an hour not building.