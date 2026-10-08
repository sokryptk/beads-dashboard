# Beads dashboard

A local page for every pending issue in a [bd (beads)](https://github.com/steveyegge/beads) tracker.
Use it to see what the agents are filing, set priorities, and clear out stale work.

```sh
python3 ~/projects/beads-dashboard/server.py --repo ~/projects/tempo
# or: cd into any repo with .beads and run it without --repo
```

It opens `http://127.0.0.1:7766/`. Switch folders from the box at the top. You can type a path (`~` works) or pick a
nearby repo that has a `.beads` dir. The folder is kept in the URL, so each tab can show a different repo.

## What it does

A Linear-style app: a sidebar of views, an inset main panel, and an issue view with a properties sidebar.

- **Folder switcher** (top left): pick a nearby repo with a `.beads` dir, or type any path and press Enter.
- **Board** (the default view): To do, In progress, Blocked and Done (the last 3 days). Drag cards between
  columns to start, stop, close or reopen them. Blocked follows dependencies, so you can't drop cards into it.
  Epics stay off the board.
- **Backlog**: "Someday" (P4) and "On ice" (deferred). Drop a card on Backlog in the sidebar to park it at P4.
- **All issues**: every open issue as a list. Use **Display** to group it by status, priority or epic and to
  change the sort order.
- **Needs you** (the `human` label) and **Gone quiet** (no update in 14 days, or in progress with no update in
  2) are saved views. **Epics** in the sidebar filter to one epic's work.
- **Filter** (`f`): add filters for priority, type, label or epic. Each one shows as a removable chip.
- **Issue view**: description, design, acceptance criteria, notes, what it's waiting on, sub-issues and
  comments. On the right is a properties sidebar (status, priority, type, assignee, epic, labels, dates) and
  actions.
- **Actions**: click a status circle or priority bars to change them. Right-click a card or row for the full
  menu: status, priority, flag "Needs you", release claim, move to backlog or board, copy, close, delete.
  Shift-click to select several; a bar appears for bulk changes. Priority, move, close and defer changes offer
  Undo. **Delete** is permanent; it first shows any dependents and offers "Close instead".
- **Copy**: copy as Markdown, copy the ID, or copy a ready-made agent prompt.

The page refreshes every 20 s. Shortcuts: `1`–`5` switch views, `/` searches, `f` opens filters, `r`
refreshes, `Esc` closes.

## How it works

`server.py` (Python 3 standard library only) runs the real `bd … --json` CLI in the chosen folder. Every
change goes through bd, so the dashboard keeps no state of its own. It listens only on 127.0.0.1, rejects
foreign `Host` headers, and requires a per-run token on every write. Issue IDs and inputs are validated, and
arguments are passed without a shell.

Options: `--port 7766`, `--no-open`.

## License

MIT. See [LICENSE](LICENSE).
