# Scheduled Runner Cron/Systemd Dry-Run Guide

This guide shows how to schedule the read-only diagnostics runner in
`--dry-run` mode only. It is documentation only: nothing in this repository
installs a cron entry, creates a systemd unit, enables a timer, or starts a
scheduled job automatically.

The scheduled command below only prints the runner's planned read-only
diagnostic commands. It does not create runner lock files, does not create
runner logs, does not run child diagnostics, does not write reports, and does
not write the runtime DuckDB database.

Safety boundary:

- No wallet
- No private key
- No seed phrase
- No signing
- No swap
- No LP add/remove
- No rebalance
- No live execution
- No signal generation
- No paper position creation
- No `future_position_events` writes

## Paths

Repository path used by the examples:

```bash
/home/ubuntu/projects/dlmm-research
```

Runtime database path passed to the runner:

```bash
/home/ubuntu/projects/dlmm-research/runtime/dlmm.duckdb
```

Cron dry-run shell lock path used by the examples:

```bash
/home/ubuntu/projects/dlmm-research/runtime/locks/scheduled_readonly_runner_cron_dry_run.lock
```

Cron dry-run shell log path used by the examples:

```bash
/home/ubuntu/projects/dlmm-research/runtime/logs/scheduled_readonly_runner_cron_dry_run.log
```

Systemd dry-run shell lock path used by the examples:

```bash
/home/ubuntu/projects/dlmm-research/runtime/locks/scheduled_readonly_runner_systemd_dry_run.lock
```

Systemd dry-run shell log path used by the examples:

```bash
/home/ubuntu/projects/dlmm-research/runtime/logs/scheduled_readonly_runner_systemd_dry_run.log
```

The runner's built-in non-dry-run defaults remain:

```bash
lock dir: runtime/locks
lock file: runtime/locks/scheduled_readonly_runner.lock
log dir:  runtime/logs
log file: runtime/logs/scheduled_readonly_runner_<run_id>.log
```

In `--dry-run` mode, the runner intentionally does not create its built-in
lock file or per-run log file. The cron/systemd examples therefore use
`flock` and shell redirection around the dry-run command so scheduled dry-run
checks still have an overlap guard and an operator-visible log.

## One-Time Manual Dry Run

Run this before installing any scheduler entry:

```bash
cd /home/ubuntu/projects/dlmm-research
python3 scripts/run_scheduled_readonly_diagnostics.py \
  --dry-run \
  --db-path runtime/dlmm.duckdb
```

Expected behavior:

- prints the safety banner
- prints planned read-only commands
- exits `0`
- creates no runner lock file
- creates no runner log file
- runs no child diagnostics
- writes no reports
- writes no database rows

## Cron Dry-Run Example

This example schedules the dry-run check every six hours. It uses `flock` so a
slow or stuck dry-run wrapper cannot overlap with the next scheduled dry-run.

Create the runtime directories first:

```bash
mkdir -p /home/ubuntu/projects/dlmm-research/runtime/locks
mkdir -p /home/ubuntu/projects/dlmm-research/runtime/logs
```

Open the current user's crontab:

```bash
crontab -e
```

Add exactly this entry if you intentionally want to enable the dry-run schedule:

```cron
17 */6 * * * cd /home/ubuntu/projects/dlmm-research && /usr/bin/flock -n /home/ubuntu/projects/dlmm-research/runtime/locks/scheduled_readonly_runner_cron_dry_run.lock /usr/bin/python3 scripts/run_scheduled_readonly_diagnostics.py --dry-run --db-path runtime/dlmm.duckdb >> /home/ubuntu/projects/dlmm-research/runtime/logs/scheduled_readonly_runner_cron_dry_run.log 2>&1
```

Inspect installed cron entries:

```bash
crontab -l
```

Inspect the cron dry-run log:

```bash
tail -n 80 /home/ubuntu/projects/dlmm-research/runtime/logs/scheduled_readonly_runner_cron_dry_run.log
```

Disable or remove the cron dry-run schedule:

```bash
crontab -e
```

Delete the line that starts with:

```cron
17 */6 * * * cd /home/ubuntu/projects/dlmm-research
```

Confirm removal:

```bash
crontab -l | grep -F "run_scheduled_readonly_diagnostics.py --dry-run" || true
```

Optional cleanup after disabling cron:

```bash
rm -f /home/ubuntu/projects/dlmm-research/runtime/locks/scheduled_readonly_runner_cron_dry_run.lock
rm -f /home/ubuntu/projects/dlmm-research/runtime/logs/scheduled_readonly_runner_cron_dry_run.log
```

## Systemd User Timer Dry-Run Example

This example uses a user-level systemd service and timer. It schedules the same
dry-run command every six hours. Do not use `sudo` for these `systemctl --user`
commands.

Create the runtime and user systemd directories:

```bash
mkdir -p /home/ubuntu/projects/dlmm-research/runtime/locks
mkdir -p /home/ubuntu/projects/dlmm-research/runtime/logs
mkdir -p ~/.config/systemd/user
```

Create `~/.config/systemd/user/dlmm-scheduled-readonly-dry-run.service`:

```ini
[Unit]
Description=DLMM scheduled read-only diagnostics dry run

[Service]
Type=oneshot
WorkingDirectory=/home/ubuntu/projects/dlmm-research
ExecStart=/usr/bin/flock -n /home/ubuntu/projects/dlmm-research/runtime/locks/scheduled_readonly_runner_systemd_dry_run.lock /usr/bin/python3 scripts/run_scheduled_readonly_diagnostics.py --dry-run --db-path runtime/dlmm.duckdb
StandardOutput=append:/home/ubuntu/projects/dlmm-research/runtime/logs/scheduled_readonly_runner_systemd_dry_run.log
StandardError=append:/home/ubuntu/projects/dlmm-research/runtime/logs/scheduled_readonly_runner_systemd_dry_run.log
```

Create `~/.config/systemd/user/dlmm-scheduled-readonly-dry-run.timer`:

```ini
[Unit]
Description=Run DLMM scheduled read-only diagnostics dry run every six hours

[Timer]
OnCalendar=*-*-* 00/6:17:00
Persistent=false
Unit=dlmm-scheduled-readonly-dry-run.service

[Install]
WantedBy=timers.target
```

Load and start the timer only if you intentionally want to enable the dry-run
schedule:

```bash
systemctl --user daemon-reload
systemctl --user enable --now dlmm-scheduled-readonly-dry-run.timer
```

Inspect timer status:

```bash
systemctl --user list-timers dlmm-scheduled-readonly-dry-run.timer
systemctl --user status dlmm-scheduled-readonly-dry-run.timer
```

Run the systemd dry-run service once manually:

```bash
systemctl --user start dlmm-scheduled-readonly-dry-run.service
```

Inspect the systemd dry-run log:

```bash
tail -n 80 /home/ubuntu/projects/dlmm-research/runtime/logs/scheduled_readonly_runner_systemd_dry_run.log
```

Disable and stop the systemd dry-run timer:

```bash
systemctl --user disable --now dlmm-scheduled-readonly-dry-run.timer
```

Remove the systemd dry-run unit files:

```bash
rm -f ~/.config/systemd/user/dlmm-scheduled-readonly-dry-run.timer
rm -f ~/.config/systemd/user/dlmm-scheduled-readonly-dry-run.service
systemctl --user daemon-reload
systemctl --user reset-failed
```

Confirm removal:

```bash
systemctl --user list-timers | grep -F "dlmm-scheduled-readonly-dry-run" || true
systemctl --user list-unit-files | grep -F "dlmm-scheduled-readonly-dry-run" || true
```

Optional cleanup after disabling systemd:

```bash
rm -f /home/ubuntu/projects/dlmm-research/runtime/locks/scheduled_readonly_runner_systemd_dry_run.lock
rm -f /home/ubuntu/projects/dlmm-research/runtime/logs/scheduled_readonly_runner_systemd_dry_run.log
```

## Safety Checklist

Before enabling either example:

- Confirm the scheduled command includes `--dry-run`.
- Confirm the command is `scripts/run_scheduled_readonly_diagnostics.py`, not any wallet,
  trading, execution, swap, LP, rebalance, or paper-position command.
- Confirm the command uses `/usr/bin/flock -n` with the documented dry-run lock path.
- Confirm logs are redirected only under `runtime/logs/`.
- Confirm the runtime DB path is `runtime/dlmm.duckdb`.
- Confirm no secrets or credentials are placed in cron, systemd unit files, environment
  files, or logs.
- Confirm `future_position_events` remains a reserved/display-only table and the dry-run
  schedule writes no rows.
- Confirm generated runtime logs remain local and are not committed.

After enabling either example:

- Check `crontab -l` or `systemctl --user list-timers` for the single expected dry-run
  schedule.
- Check the dry-run log for the safety banner and planned command list.
- Check that no runner built-in lock file was created by dry-run:

```bash
test ! -e /home/ubuntu/projects/dlmm-research/runtime/locks/scheduled_readonly_runner.lock
```

- Check that no runner per-run log file was created by dry-run:

```bash
find /home/ubuntu/projects/dlmm-research/runtime/logs -maxdepth 1 -name 'scheduled_readonly_runner_*.log' -print
```

- If any command omits `--dry-run`, stop the timer or remove the cron entry before
  investigating further.
