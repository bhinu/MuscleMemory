# MuscleMemory

A browser agent that learns from being corrected.

When an automated agent gets stuck on a web page, the usual options are bad: fail
and page a human, or retry blindly and hope. MuscleMemory takes a third path —
a human fixes it once, by hand, and the system records enough about that fix to
replay it the next time the same wall shows up.

The name is the idea: a motion you performed deliberately once becomes something
you can do without thinking.

> **Status: early.** This is a learning project, built one piece at a time. The
> design below is the target, not a description of working software. Nothing
> here is implemented yet.

## The three pieces

**The chaos portal** — a fake supplier ordering site, served by FastAPI. Its
reason to exist is that I can break it on purpose. Real sites get redesigned
without telling you: a button moves, a field gets renamed, a confirmation step
appears. Testing against a site I don't control means waiting around for that to
happen. Testing against one I do control means I can cause it on demand, and
cause the *same* change twice.

**The agent** — drives a real browser through Playwright and decides what to do
next by asking an LLM. It places orders on the portal. When it can't figure out
the next move, it stops and says so.

**The memory layer** — SQLite. When the agent gets stuck and a human steps in,
the fix is recorded. Next time the agent hits the same wall, it checks memory
before it asks the model.

### Dangerous actions are never auto-retried

Some actions are reversible and some aren't. Re-reading a page costs nothing.
Submitting a purchase order might cost real money, and doing it twice because a
retry loop couldn't tell the difference is exactly the failure mode that makes
people distrust agents.

So the dangerous ones are marked, and they don't get replayed from memory
without a human present. A remembered fix can carry the agent up to the edge of
an order submission. It doesn't carry it over.

### Fixes are anchored to landmarks, so stale ones get caught

The naive version of this memory layer stores "click the button at coordinates
(420, 310)" and replays it forever. That works right up until the page changes,
and then it silently clicks the wrong thing — which is worse than not
remembering at all, because now the system is confidently wrong.

Instead, each saved fix is tied to a page *and* to a landmark: some feature of
the page that ought to still be there if the fix is still valid. Before replaying,
the system looks for the landmark. Gone or changed, the fix is treated as stale
and the agent asks for help again rather than acting on an outdated memory.

The goal is that outdated fixes get **detected**, not replayed.

## Stack

| Piece | Tool |
|---|---|
| Portal | Python + FastAPI |
| Browser control | Playwright |
| Storage | SQLite |
| Agent decisions | OpenAI API |
