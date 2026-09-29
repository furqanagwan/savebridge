# savebridge

Move PC game saves between **Steam** and **Xbox PC** (Game Pass / Microsoft Store),
in either direction, and between accounts, including saves someone else sent you.

Pure Python 3.10+, no dependencies. Windows only (that's where both stores live).

## Supported games

Every game supports both directions (Steam → Xbox and Xbox → Steam), plus
importing saves from other accounts into either platform.

| id | Game | Steam app | Xbox package | Steam → Xbox | Xbox → Steam |
|---|---|---|---|---|---|
| `mgs-delta` | METAL GEAR SOLID Δ: SNAKE EATER | 2417610 | `KonamiDigitalEntertainmen.RG5` | ✅ verified in game | ✅ tested on real saves* |

\* Converted and verified byte-for-byte against real save files; not yet
loaded in the Steam build.

## Usage

Close the game first on both platforms. Every write backs up the target folder
to `%LOCALAPPDATA%\savebridge\backups\<game>\` as a zip, then reads the result
back to verify it.

```powershell
python -m savebridge games                          # supported games
python -m savebridge accounts mgs-delta             # Steam/Xbox accounts found on this PC
python -m savebridge list mgs-delta                 # saves on both sides, side by side

# Your own saves, this PC
python -m savebridge convert mgs-delta steam-to-xbox --dry-run
python -m savebridge convert mgs-delta steam-to-xbox
python -m savebridge convert mgs-delta xbox-to-steam --only slot1,slot3

# Someone else's save (a zip, a folder, loose files, Steam or Xbox format)
python -m savebridge import mgs-delta C:\Downloads\100percent.zip --to xbox
python -m savebridge import mgs-delta C:\Downloads\save --to steam --slot-map 1:8

# Share yours
python -m savebridge export mgs-delta --from xbox --out C:\Temp\my-saves
```

Options shared by the commands that write:

| option | meaning |
|---|---|
| `--only slot1,autosave` | copy just these saves |
| `--all` | also copy optional saves (for MGS Δ: `profile` unlocks and `settings`) |
| `--slot-map 3:7,4:8` | put source slot 3 in slot 7, and so on |
| `--steam-account ID` | SteamID64, account ID or `[U:1:n]`; default is the signed-in user |
| `--xbox-account XUID` | needed only when several Xbox profiles have played the game |
| `--dry-run` | show what would change |

**Importing from other accounts.** Saves are recognised by their contents, not
their file names or folders, so a Steam folder named after someone else's
SteamID, a raw Xbox `wgs` folder, or a zip of either all work. They are written
into *your* account's location with the target platform's encoding.

**Xbox:** the game must have been started once on the target Xbox profile so
its save folder exists. New containers are marked "created" and updated ones
"modified", so they are uploaded rather than replaced by the cloud copy. The
upload happens while the game is running: launch it online, wait at the main
menu for a minute, and quit from the menu. `savebridge list` still works
locally before then, but other devices won't see the saves until they upload.
If the Xbox app asks about a conflict, keep the copy on this PC.

**Steam:** if Steam Cloud reports a conflict on the next launch, keep the local
files.

## How it works per game

### METAL GEAR SOLID Δ: SNAKE EATER

Both builds write identical Unreal Engine GVAS data with an 18-byte trailer:

```
u64 magic    0xD42AEE521DA13C62
u64 check    CityHash64(all preceding bytes), obfuscated
u8  0
u8  version  Steam = 2, Xbox = 1
```

Version 1 stores `hash ^ magic ^ 0x100`. Version 2 stores
`ror15(ror15(hash ^ 0x09EBF7FD217247F5) ^ magic ^ 0x200) ^ 0x875CB4716484CC12`.
No account ID is stored in the save.

| | Steam | Xbox |
|---|---|---|
| Location | `%LOCALAPPDATA%\MGSDelta\Saved\SaveGames\<SteamID64>\` | `%LOCALAPPDATA%\Packages\KonamiDigitalEntertainmen.RG5_*\SystemAppData\wgs\<XUID>_<SCID>\` |
| Slot N | `SaveGamesN_0.sav` / `_1.sav` (alternating copies; newest `CreatedTime` wins) | container `SaveGames<NN><24 random hex>`, blob `Data` |
| Autosave | `SaveGamesAutoSave_0/1.sav` | `SaveGamesAutoSave` |
| Profile | `UserProfile_0/1.sav` | `UserProfile` |
| Settings | `UserSettings_0/1.sav` | `UserSettings` |

`LocalUserSettings` (graphics, per machine) is left alone.

## Adding a game

1. Create `savebridge/games/<game>.py` with a `Game` subclass (see
   `games/base.py` for the contract and `games/mgs_delta.py` for an example):
   - `steam_dir(account)`: where that Steam account's saves live
   - `read_steam` / `write_steam`: Steam files <-> logical saves
   - `xbox_key` / `xbox_container` / `decode_xbox` / `encode_xbox`: WGS containers <-> logical saves
   - `identify(data, name)`: recognise a loose file from either platform (powers `import`)
   - optional: `remap` (slot moves), `rebind` (games that embed a SteamID/XUID in the save)
2. Register it in `savebridge/games/__init__.py`.
3. Add tests with synthetic saves under `tests/`. Don't commit real save files.

The WGS container format itself (`savebridge/wgs.py`) is shared by every Xbox PC
game and supports multi-blob containers.

## Tests

```powershell
python -m unittest discover -s tests -t .
```
