---
name: New provider
about: Add support for another agent CLI or billed API
labels: provider
---

**Which tool?** Name and a link.

**Where does it keep usage on disk?**
Path glob, and a redacted sample line showing the token fields.

**How is plan quota reachable?**
A slash command in its TUI, a documented API, or not at all.

**Does reading quota consume any allowance?**
If you do not know, say so. For X this was settled by calling the endpoint twice
and confirming the reported usage did not move - that kind of check belongs in
the code, not in someone's memory.

**Does it report percent USED or percent REMAINING?**
Codex reports remaining and is inverted in its provider. Getting this backwards
makes an exhausted account look healthy.
