# Squad timers (systemd user units)

Scheduled starts for the Office squad. They are **not enabled** by the repo; enable them when you are ready.

| Unit | When | What it runs |
|------|------|--------------|
| `synthia-squad-office-daily.timer` | weekdays 07:30 local | `synthia-squad start office "Daily board sweep: ..." --slug board-sweep` (nudges stay drafts) |
| `synthia-squad-office-monthly.timer` | 1st of each month, 08:00 local | `synthia-squad start office "Monthly investor update for the previous month ..." --slug investor-update` |

The release squad is on demand only (`synthia-squad start release "v3.2 ..."` or by voice).

## Prerequisites

- `synthia-squad` at `~/.local/bin/synthia-squad` and the squads installed: `synthia-squad install office`.
- herdr running (the units start the director in a herdr pane) and a graphical session that can open it. The timers use `Persistent=true`, so a missed run starts at the next login.

## Enable

```bash
mkdir -p ~/.config/systemd/user
cp deploy/squads/*.service deploy/squads/*.timer ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now synthia-squad-office-daily.timer
systemctl --user enable --now synthia-squad-office-monthly.timer
systemctl --user list-timers 'synthia-squad-*'
```

## Test one run now

`systemctl --user start synthia-squad-office-daily.service` then `synthia-squad status`.

## Disable

`systemctl --user disable --now synthia-squad-office-daily.timer synthia-squad-office-monthly.timer`

## Sending nudges

The daily brief says nudges are drafts. To let the PM send Slack DMs, edit the `ExecStart` brief in the service file to add the line `nudges: send`. Do this only after you have read a week of `out/nudges.md`.
