# savebridge

Move PC game saves between **Steam** and **Xbox PC** (Game Pass / Microsoft
Store), in either direction and between accounts, including saves someone
else shared. Windows only. There is a desktop app (`app/`) and a command line.

> **Disclaimer.** savebridge is an unofficial fan project, not affiliated with
> Microsoft, Valve or any game publisher. It edits save files: it backs up
> everything it changes and verifies what it writes, but use it at your own
> risk. Only use saves you have the right to use, and don't use it to cheat in
> online or competitive modes.

## Games confirmed working

"Verified" means a converted save loaded in the game. Every game converts in
both directions and imports downloaded saves into either store; the Xbox →
Steam direction is covered by tests on synthetic saves.

| Game | Steam → Xbox | Notes |
|---|---|---|
| METAL GEAR SOLID Δ: SNAKE EATER | ✅ verified | |
| Destroy All Humans! (2020) | ✅ verified | Steam and Xbox share one save folder; *Reprobed* saves are refused |
| CONTROL Resonant | ✅ verified | |
| Samson: A Tyndalston Story | ✅ verified | |
| The Blood of Dawnwalker | ✅ verified | |
| Call of Duty: Black Ops II (campaign) | ✅ verified | |
| Call of Duty: Ghosts (campaign) | ⚠️ partly | the save loads; mission select and the Rorke Files live in the profile |
| Kingdom Come: Deliverance II | ✅ verified | |
| Crimson Desert | ✅ verified | |
| SILENT HILL 2 (2024) | ✅ verified | |
| FINAL FANTASY VII REMAKE INTERGRADE | ✅ verified | |
| FINAL FANTASY VII REBIRTH | ✅ verified | |
| Dispatch | ✅ verified | |
| Beast of Reincarnation | ✅ verified | |
| Cuphead | ✅ verified | |
| MOUSE: P.I. For Hire | ✅ verified | |
| Onimusha: Way of the Sword | ✅ verified | Capcom encryption; the Xbox version must have saved once |
| Halo: Campaign Evolved | ✅ verified | Solo checkpoints; the Xbox profile must have saved once |

Not supported yet: Resonance: A Plague Tale Legacy (the Xbox encryption key
is unknown), other Capcom RE Engine games (same converter, need their Xbox
details). See [research.md](research.md) for how each game stores its saves.

Halo: Campaign Evolved is available as `halo-campaign-evolved` (alias `halo`),
with Steam → Xbox loading confirmed in game. Build its separate Oodle decoder
with `./native/build_ooz.ps1`
(Visual Studio C++ tools and Git required), or set `SAVEBRIDGE_OOZ` to an
existing ooz executable. Import checkpoints together with `Progress.sav`.
The Xbox profile must have saved once so its player mapping can be recovered.
Only the observed solo checkpoint layout is supported. Rebound checkpoints
use larger, uncompressed Oodle blocks. The default Steam destination is
`%LOCALAPPDATA%\Meteorite\Saved\SaveGames`; native Steam folder discovery
has not been confirmed on an installed Steam build.

## Achievements

A converted save never stops achievements from unlocking, but it only unlocks
what the game awards from that point on:

- **Title-managed achievements** (most games) are awarded by the game itself.
  Many games re-check them when a save loads or a chapter ends, so some may pop
  soon after loading an imported save.
- **Event-based achievements** (e.g. Halo MCC, Forza Horizon 3) are counted by
  Xbox Live's servers from events the game sends while you play. A save file
  can't carry that progress, so you have to do those things again.
- Story and ending achievements unlock for the parts you play **after** the
  save point. Pick a save just before what you still need.

The app shows which kind each of your games uses. More detail:
[research.md § 8](research.md#8-achievements-title-managed-and-event-based).

## Using it

Close the game first. Every write backs up the target to
`%LOCALAPPDATA%\savebridge\backups\` and reads the result back to verify it.

```powershell
python -m savebridge games                                      # supported games
python -m savebridge list cuphead                               # saves on both stores
python -m savebridge convert cuphead steam-to-xbox --dry-run    # your own saves, this PC
python -m savebridge import cuphead C:\Downloads\save.zip --to xbox --slot-map 0:1
python -m savebridge backups                                    # backups made so far
python -m savebridge restore cuphead                            # undo the last write
```

- For Xbox, start the game once on your Xbox profile first. After writing,
  start it online so the save uploads; if the Xbox app reports a conflict,
  keep the copy on this PC.
- `--only`, `--all`, `--slot-map`, `--steam-account`, `--xbox-account` and
  `--dry-run` are explained by `python -m savebridge <command> -h`.
- Capcom games need `savebridge\_native\dsss_find.dll`; build it with
  `native\build.cmd` (Visual Studio C++ tools) or use a release build.

## Development

- [research.md](research.md): Xbox save internals and per-game formats.
- Adding a game: subclass `Game` in `savebridge/games/` (most Unreal games only
  need a file list, see `samson.py`), register it in `games/__init__.py`, add
  tests with synthetic saves. Never commit real save files.
- Tests: `python -m unittest discover -s tests -t .`

## License

[MIT](LICENSE). Third-party code: [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
