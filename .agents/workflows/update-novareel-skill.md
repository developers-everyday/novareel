---
description: How to update the NovaReel agent quickstart skill after major changes
---

# Update NovaReel Quickstart Skill

Run this workflow whenever a major change happens to the application, such as:
- A new AWS service is integrated (e.g. S3, SQS, new Bedrock model)
- A new API endpoint is added or removed
- A pipeline step is added, changed, or removed
- A new required environment variable is introduced
- A known gotcha is resolved or a new one is discovered
- The storage backend or queue backend changes

## Steps

1. Read the current skill file to understand its structure:
   `view_file /Users/rajatsingh/Documents/Projects/marketting-tool/.agents/skills/novareel-quickstart/SKILL.md`

2. Identify which sections need updating based on what changed:
   - **Stack at a Glance** — new services or model versions
   - **Repository Layout** — new files or folders
   - **Key Environment Variables** — new or renamed env vars
   - **Generation Pipeline** — new or changed steps
   - **Known Gotchas** — resolved issues (remove) or new discoveries (add)
   - **Pending Work** — mark completed items done, add new planned features

3. Edit the skill file with the minimal accurate changes. Keep it concise — this is a quick-start, not docs.

4. Commit the updated skill alongside the code change:
   ```bash
   git add .agents/skills/novareel-quickstart/SKILL.md
   git commit -m "docs: update novareel-quickstart skill — <brief reason>"
   ```
