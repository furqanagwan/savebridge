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
| `destroy-all-humans` (`dah`) | Destroy All Humans! (2020) | 803330 | `NordicGames.DestroyAllHumans` | ✅ verified in game | ✅ same files† |
| `control-resonant` (`control`) | CONTROL Resonant (Play Anywhere) | 3669870 | `Remedy.CONTROLResonant` | ✅ verified in game | 🧪 tested on synthetic saves |
| `samson` | Samson: A Tyndalston Story | 3634520 | `29692LiquidSwords.CriminalJustice` | ✅ verified in game | 🧪 tested on synthetic saves |
| `dawnwalker` | The Blood of Dawnwalker | 3751260 | `NAMCOBANDAIGamesInc.TheBloodofDawnwalker` | ✅ verified in game | 🧪 tested on synthetic saves |

\* Converted and verified byte-for-byte against real save files; not yet
loaded in the Steam build.
† Both builds write identical files to the same folder, so a save from either
works in both; use `import` to bring saves in from elsewhere.

Not supported: Destroy All Humans! 2 – Reprobed. It uses the same save classes
but a newer engine, and Destroy All Humans! (2020) hangs if given one of its
saves, so `import dah` refuses them.

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

# Destroy All Humans!: a downloaded save into the Xbox version
python -m savebridge import dah C:\Downloads\DH.zip --to xbox --dry-run
python -m savebridge import dah C:\Downloads\DH.zip --to xbox
python -m savebridge import dah C:\Downloads\DH.zip --to xbox --slot-map 1:2   # as DevAutoSave_2
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

### Destroy All Humans! (2020)

Steam and Xbox run the same build (Unreal Engine 4.22.3) and write plain GVAS
files with identical headers, no checksum and no account ID, to the same
per-PC folder. The Xbox build does not use Xbox cloud saves.

| File in `%LOCALAPPDATA%\DH\Saved\SaveGames\` | Class | Contents |
|---|---|---|
| `DevAutoSave_<N>.sav` | `BFGCore.BFGSaveGame` | progress; key `DevAutoSave_<N>` |
| `SaveOptions.sav` | `BFGCore.BFGSaveOptions` | settings, key bindings, unlocked skins, last used save; key `options` |

Importing `options` merges instead of replacing it: your settings stay, the
unlocked skins (`m_profileUnlockTags`) are combined, and "last used save" points
at the newest imported save so Continue loads it.

### CONTROL Resonant

Every save file is a Remedy RMDB blob with the same bytes on both platforms:
`'RMDB'`, `u32 2`, `u32 2`, `u32 crc32(bytes 16..end)`, payload. A slot is a set
of save points (`auto-N`, `key-<id>`, `return`), each split into `-header`
(Unix time at offset 20 plus the area path), `-player`, `-persi-global` and
`-bundle-container`. No account ID is stored.

| | Steam | Xbox |
|---|---|---|
| Location | `Steam\userdata\<account id>\3669870\remote\` | WGS container per slot, one blob per file |
| Slot 0 | `slot-0_<point>-<part>` files | container `slot-0`, blobs `<point>-<part>` |
| Preferences | `preferences_data` (settings, raw), `preferences_savegame` (continue pointer) | container `preferences`, blobs `data`, `savegame` |
| Achievements | (Steam's own) | container `achievements`, left alone |

A slot is replaced as a whole, so save points from two playthroughs never mix.
Importing `preferences` keeps the target's settings and takes only the continue
pointer. This is a **Play Anywhere** title: anything written to Xbox syncs to
Xbox consoles on the same account.

### Samson: A Tyndalston Story

Unreal Engine 5.7 on both stores, identical GVAS files and custom-version
tables, no checksum, no account ID. The most common Unreal layout: one `.sav`
per Xbox container, same bytes, blob `Data`.

| File (`%LOCALAPPDATA%\Samson\Saved\SaveGames\`, per PC) | Xbox container | Copied |
|---|---|---|
| `SaveGame.sav`, `SaveGame_Checkpoint_StartOfDay.sav`, `SaveGameManifest.sav` | same names | always, and only together |
| `SharedGameSettings.sav`, `EnhancedInputUserSettings.sav` | same names | with `--all` |

There is a single save slot. Downloads often bundle several save sets; the
importer refuses a folder holding more than one, so point it at the one you want.

### The Blood of Dawnwalker

Each save is three files with the same bytes on both stores; no account ID.

| Steam (`%LOCALAPPDATA%\Dawnwalker\Saved\SaveGames\`, per PC) | Xbox container `<Name>` | Contents |
|---|---|---|
| `<Name>.sav` | blob `Data` | game state (Rebel Wolves' chunked `DSAV` format) |
| `<Name>.meta` | blob `Meta` | JSON shown in the load menu: day, play time, date, build, and `SaveName`/`Type`/`TypeString` |
| `<Name>.png` | blob `SaveIcon` | screenshot |

`<Name>` is `ManualSave<N>`, `Autosave<N>` or `FinalAutosave`. The `.sav` doesn't
record its slot, so `--slot-map` moves a save by rewriting just those three
meta fields. To add a downloaded save without overwriting yours, map it to a
free manual slot, e.g. `--slot-map 18:31`. The Xbox-only `RebelSettings`
container is left alone.

## Adding a game

Most Unreal Engine games store one `.sav` per Xbox container. For those,
subclass `UnrealFilesGame` (`games/unreal_files.py`) and list the files, as
`games/samson.py` does; that's usually all it takes.

Otherwise:

1. Create `savebridge/games/<game>.py` with a `Game` subclass (see
   `games/base.py` for the contract; `games/mgs_delta.py` is an Xbox cloud save
   example and `games/destroy_all_humans.py` a plain-file one):
   - `save_dir(platform, account)`, `read_files` / `write_files`: save files <-> logical saves
   - if the Xbox build uses Xbox cloud saves (`xbox_uses_wgs = True`, the default):
     `xbox_key` / `xbox_container` / `decode_xbox` / `encode_xbox`
   - `steam_per_account = False` if saves are per PC rather than per SteamID
   - `identify(data, name)`: recognise a loose file from either platform (powers
     `import`); refuse lookalike saves from other games here
   - optional: `prepare` (merge with the target's existing saves), `remap` (slot
     moves), `rebind` (games that embed a SteamID/XUID in the save), `slot_key`
2. Register it in `savebridge/games/__init__.py`.
3. Add tests with synthetic saves under `tests/`. Don't commit real save files.

Shared helpers: `savebridge/wgs.py` (Xbox cloud save containers, including
multi-blob) and `savebridge/unreal.py` (reading and patching UE4/UE5 GVAS saves).
`import` accepts a raw Xbox save folder (`...\SystemAppData\wgs\<XUID>_<id>`)
as well as Steam files; blobs are named `<container>/<blob>` for `identify`.

## Tests

```powershell
python -m unittest discover -s tests -t .
```
