# Scheduling

`com.edgetournament.hourly.plist` runs one live cycle at minute 3 of every hour.
`com.edgetournament.weekly.plist` judges the challenger, re-searches and sends the
digest on Sundays at 03:30.

Both templates carry `__HOME__` as a placeholder rather than a hard-coded home
directory. Substitute your own and install:

```bash
for f in launchd/com.edgetournament.*.plist; do
  sed "s|__HOME__|$HOME|g" "$f" > ~/Library/LaunchAgents/$(basename "$f")
  launchctl load ~/Library/LaunchAgents/$(basename "$f")
done
```

Remove with `launchctl unload ~/Library/LaunchAgents/com.edgetournament.*.plist`.
Logs are written to `state/`.
