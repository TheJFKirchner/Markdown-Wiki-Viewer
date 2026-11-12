## Wikis

There are two wikis. The personal wiki records my work: sessions, decisions, and where each project or analysis stands. Each piece of work is a topic, with its own page, and tags connect related topics. The team wiki is the reference for our data and methods: which source to use for what, what each table is, how analyses are done.

- Before starting an analysis, a data question, or work on an existing project, use the `wiki-lookup` agent with a one or two sentence description of the task, then read the pages it returns. Do not read either wiki's `index.md` yourself; the agent exists to keep it out of this conversation.
- When the lookup returns a subject-area page, follow its "Which source to use" guidance unless I say otherwise, and tell me if what you find in the data contradicts it.
- Do not write to either wiki directly. Sessions are captured into the personal wiki by the `wiki-capture` skill. The team wiki changes only through the `team-wiki-manager` skill or WikiApp's Promotion tab, when I ask for it, and I review every change.
- If you learn something about a table or data source that the wiki does not say or gets wrong, tell me in your reply. It will be picked up when the session is captured.
