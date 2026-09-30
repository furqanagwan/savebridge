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
| `black-ops-2` (`bo2`) | Call of Duty: Black Ops II — campaign | 202970 | `38985CA0.CallofDutyBlackOps2PCMS` | ✅ verified in game | 🧪 tested on synthetic saves |
| `ghosts` | Call of Duty: Ghosts — campaign | 209160 | `38985CA0.CallofDutyGhostsPCMS` | ⚠️ save loads; mission unlocks are in the profile‡ | 🧪 tested on synthetic saves |
| `kcd2` | Kingdom Come: Deliverance II | 1771300 | `DeepSilver.77536C3FE941` | ✅ verified in game | 🧪 tested on synthetic saves |
| `crimson-desert` | Crimson Desert | 3321460 | `PearlAbyss.CrimsonDesert` | ✅ verified in game | 🧪 tested on synthetic saves |
| `silent-hill-2` (`sh2`) | SILENT HILL 2 (2024) | 2124490 | `KonamiDigitalEntertainmen.SILENTHILL2` | ✅ verified in game | 🧪 tested on synthetic saves |
| `ff7-remake` (`ff7`) | FINAL FANTASY VII REMAKE INTERGRADE | 1462040 | `39EA002F.EXED1` | ✅ verified in game | 🧪 tested on synthetic saves |
| `ff7-rebirth` (`rebirth`) | FINAL FANTASY VII REBIRTH | 2909400 | `39EA002F.EXED2` | ✅ verified in game | 🧪 tested on synthetic saves |
| `dispatch` | Dispatch | 2592160 | `AdHocStudio.DispatchSeason1` | ✅ verified in game | 🧪 tested on synthetic saves |
| `beast-of-reincarnation` (`bor`) | Beast of Reincarnation | 2001760 | `Fictions.ProjectAibou` | ✅ verified in game | 🧪 tested on synthetic saves |
| `mouse-pi` (`mouse`) | MOUSE: P.I. For Hire | 2416450 | `PlaySideStudiosLTD.MOUSEP.I.ForHire` | ✅ verified in game | 🧪 tested on synthetic saves |

‡ Ghosts' `savegame.svg` is only the Continue point. Mission select reads the
profile (`settings_s.zip.iw6`), which Steam downloads usually don't include.

\* Converted and verified byte-for-byte against real save files; not yet
loaded in the Steam build.
† Both builds write identical files to the same folder, so a save from either
works in both; use `import` to bring saves in from elsewhere.

Not supported: Destroy All Humans! 2 – Reprobed. It uses the same save classes
but a newer engine, and Destroy All Humans! (2020) hangs if given one of its
saves, so `import dah` refuses them.

## Hard cases: not (yet) in savebridge

### Resonance: A Plague Tale Legacy (Steam 2713000, Xbox `FocusHomeInteractiveSA.APlagueTaleFelons`): blocked

Every file (`slot00`, `slot01`, `settings`, `inputprofile`) is encrypted in
full, with no readable header, on both stores.

| | Steam | Xbox |
|---|---|---|
| Storage | `Steam\userdata\<account>\2713000\remote\` | WGS container per file, blob `data` |
| Cipher | AES-128-CBC, zero IV, PKCS#7; key = first 16 bytes of SHA-1(`asobo` + 24 × `3` + `asobo`)¹ | AES-sized blocks (multiples of 16), **unknown key** |
| Decrypts with the Steam key | ✅ `slot00` → compressed game data, `inputprofile` → XML | ❌ padding check fails on every file |

Why it is blocked:

- **The Xbox key is not the Steam key**, and it is not an obvious variation
  of it. Roughly 4,600 candidates (the account's XUID in decimal/hex, platform
  names, the `asobo…asobo` template with other fillers, under SHA-1/MD5/SHA-256
  key derivation) were tried against a known-plaintext target: the Xbox
  `inputprofile`, which must decrypt to `<?xml`. None worked.
- **The key can't be read out of the game.** Store/Game Pass executables are
  access-locked (`C:\Program Files\WindowsApps` and `C:\XboxGames\…\Content`
  deny reads), so the Xbox build can't be inspected offline.
- **The only known working method is live memory injection**¹: attach a
  debugger to the running Xbox game, break in its save routine at a
  build-specific offset, and swap the save buffer for the decrypted Steam save
  so the game encrypts it itself. That depends on the exact game build (it
  breaks when the game updates) and needs a debugger with administrator rights,
  so it isn't something this tool automates.

What would unblock it: the Xbox key or its derivation (for example from the
Xbox build's code), after which it becomes an ordinary decrypt → re-encrypt
plugin. Steam ↔ Steam conversion is already possible with the known key.

¹ Format and the memory-injection method documented by
[ResonanceAPlagueTaleLegacySteamToGamePassSaveConvert](https://github.com/berkay496/ResonanceAPlagueTaleLegacySteamToGamePassSaveConvert).

### Onimusha: Way of the Sword (Steam 2638890, Xbox `F024294D.63383C66B8708`): works, not yet built in

Capcom RE Engine saves (`win64_save\data001Slot.bin` on Steam; WGS container
`SaveData001Slot` on Xbox) use the `DSSS` container: a 16-byte header, blocks
with an ElGamal key exchange plus AES-128-OFB, a footer, and a Murmur3-32
signature. The key is derived from an **account ID**, so a save only loads for
the account that wrote it:

- Steam: the SteamID's 32-bit account ID, run through the game's ID variant.
- Xbox: the same scheme, but the ID is **not** the account's XUID or a simple
  hash of it; it is some other per-account number.

Neither ID needs to be known in advance: both can be recovered from a save by
brute force over 2³² candidates (seconds with vectorised code), using a
known-plaintext check on the first block. A Steam → Xbox conversion therefore
works like this: recover the uploader's ID from the Steam save, recover the
target's ID from **their own existing Xbox save**, decrypt, re-encrypt, re-sign.
This was verified in game on Xbox, including the cloud upload. The crypto
comes from [MandarinJuice](https://github.com/mi5hmash/MandarinJuice) (MIT)
and still needs porting to Python before it lands in savebridge; the same work
would cover other RE Engine games (Resident Evil, Monster Hunter, Street Fighter 6).

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

### Call of Duty: Black Ops II (campaign)

| | Steam | Xbox |
|---|---|---|
| Location | `<Steam library>\steamapps\common\Call of Duty Black Ops II\players\` | WGS container `players`, one blob per file, **plus** a plain-file copy in `SystemAppData\xgs\<XUID>_<id>\players\` that the game reads (XGameSaveFiles); both are written together |
| Progress | `savegame.svg` (level name at offset 32), `savegame.foo` | same |
| Settings (`--all`) | `bindings_sp.bdg`, `user_sp.cgp`, `user_common.cgp` | same |

`savegame.foo` records its owner (SteamID or XUID) at offset 64 behind an
unidentified 4-byte checksum. It is copied unchanged: the game loads saves
owned by another account (verified on Xbox). Multiplayer and zombies have no
local progress: ranks and stats live on Activision's servers per account.

**4K on high-DPI screens:** the game isn't DPI-aware, so at 300% Windows scaling
it only sees 1280×720. Setting "Override high DPI scaling → Application"
(`~ HIGHDPIAWARE` under `HKCU\Software\Microsoft\Windows NT\CurrentVersion\AppCompatFlags\Layers`)
for `t6sp.exe`, `t6mp.exe` and `t6zm.exe` in `C:\XboxGames\Call of Duty Black Ops 2\Content\`
makes 3840×2160 available.

### Call of Duty: Ghosts (campaign)

| | Steam | Xbox |
|---|---|---|
| Location | `<Steam library>\steamapps\common\Call of Duty Ghosts\players2\` | WGS container `Gamerprofile_gdk`, **plus** the game's own copy in `<drive>:\XboxGames\Call of Duty Ghosts\Content\players2\<decimal XUID>\`; both are written together |
| Continue point | `savegame.svg` (IW6, version `0x47`, level name at offset 32; no owner ID or checksum found) | same, plus `save\internal/snd_restart.svg` (restart point, removed when the save is replaced) |
| Profile | `settings_s.zip.iw6` | same |

The profile is a `SEMV` file: 12-byte header, then 43 fields of
`id, type, value` (type 1 bool, 2 byte, 4 int32, 6 string: 4 bytes then
NUL-terminated text), no checksum. Field `0x29` is a 50-digit string, one digit
per campaign level in story order (prologue … skyway); non-zero marks the
mission complete and unlocks it in mission select (verified). Field `0x2a` is
another per-mission string whose meaning is unknown (it is not the Rorke Files).
Field `0x2b` names the save Continue loads. Editing the profile isn't automated.

### Kingdom Come: Deliverance II

| | Steam | Xbox |
|---|---|---|
| Location | `%USERPROFILE%\Saved Games\kingdomcome2\saves\playline<N>\*.whs` (per PC) | WGS container `saves/playline<N>`, one blob per `.whs` |
| Settings | (left alone) | containers `Profiles`, `Profiles/<name>` (left alone) |

A `.whs` is `0xFFFFFFFF`, a u32 length, an XML `<C_SaveGameDescription>` (save id
and type, time, level, build, DLCs and PC mods used), then compressed data. No
account ID and no playline number inside, so a playthrough can go into any free
playline. Newer builds load older saves; a save that lists DLC or mods you don't
have still loads, without those items.

Downloads can hold hundreds of saves (600+ MB), more than the Xbox cloud quota
comfortably takes. `--files newest` (or `newest:N`, or a list of names) copies
only some of them:

```powershell
python -m savebridge import kcd2 C:\Downloads\playline0_saves --to xbox --files newest --slot-map 0:1
```

### Crimson Desert

| | Steam | Xbox |
|---|---|---|
| Location | `%LOCALAPPDATA%\Pearl Abyss\CD\save\<SteamID64>\slot<N>\lobby.save`, `save.save` | container `slot<N>`, blobs `lobby`, `save` |

Both files are `SAVE` v2: a 0x80-byte header (flags, decompressed and stored
sizes, ChaCha20 nonce, HMAC-SHA256) and an LZ4-compressed, ChaCha20-encrypted
body. The key is a built-in constant mixed with the header version
([pycrimson](https://github.com/LukeFZ/pycrimson)), not the account or
platform, so files copy byte-for-byte. They don't record their slot number, so
`--slot-map` moves a save freely. Slots 0-2 are manual, 100 and up automatic.

### SILENT HILL 2 (2024)

One `.sav` per Xbox container (`%LOCALAPPDATA%\SilentHill2\Saved\SaveGames\<SteamID64>\`
on Steam). `SaveGameData_<N>` uses the game's `VASb` wrapper: header length,
`0xDEAD`, the `SHSaveGame` class, a save-point GUID and the map name, then a
zlib-compressed UE 5.1 GVAS body. New Game+ and ending setup live inside each
save; `PersistentData` only records the last slot and playthrough ID. `UcaSave`
is the account's achievement progress (counters and flags) and, like the
settings files, is only copied with `--all`. No account ID anywhere.

### FINAL FANTASY VII REMAKE INTERGRADE

| | Steam | Xbox |
|---|---|---|
| Location | `Documents\My Games\FINAL FANTASY VII REMAKE\Steam\<SteamID64>\` | container per save, blob `Data` |
| Saves | `ff7remake<NNN>.sav` (main game), `ff7remakeplus<NNN>.sav` (INTERmission), `ff7remakecommon.sav` (system, `--all`) | same names |
| Format | raw save (9,434,752 bytes per slot) | `bilz`, u32 compressed size, u32 raw size, 8 zero bytes, zlib stream of the raw save |

The only game so far where the bytes differ: Steam → Xbox compresses and Xbox →
Steam decompresses, and the raw save is identical. The game's deflate output
differs from Python's but both are standard zlib. No account ID inside. If an
account has two Xbox save folders for the game, the one holding its saves is used.

**FINAL FANTASY VII REBIRTH** uses the same raw format and naming
(`ff7rebirth<NNN>`, `ff7rebirthcommon`; Steam folder `Documents\My Games\FINAL FANTASY VII REBIRTH\Steam\<SteamID64>\`),
but its Xbox blob is a bare zlib stream with no `bilz` header, and the game
also reads a plain-file copy under `SystemAppData\xgs\`, which is written
alongside the container.

### Dispatch

One UE 4.27 `.sav` per Xbox container (`%LOCALAPPDATA%\Dispatch\Saved\SaveGames\`
on Steam, per PC). `SaveSlot<N>` (+ `_BACKUP`) is the save and `Index`
(+ `_BACKUP`) records each slot's latest scene, so they travel together;
`CloudSettings` is only copied with `--all`. Steam's `LocalOnly\<SteamID64>\*.bak`
copies are ignored. No account ID in the files.

### Beast of Reincarnation

One UE 5.4 `.sav` per Xbox container (`%LOCALAPPDATA%\BeastOfReincarnation\Saved\SaveGames\`
on Steam, per PC). Every file is an `AibouSaveDataContainer`: a GVAS shell
around a compressed payload, identical on both stores and without an account ID.
`borSaveDataNormal_<N>` and `borSaveDataNormal_AutoSave_<N>` are the saves and
`borSaveDataMeta` (+ `bup0`/`bup1`) is a single index for all of them, so slots
are only ever copied together with the index. `borSaveDataConfig` is settings
(`--all`); `borSaveDataLocalConfig` is per machine and left alone.

### MOUSE: P.I. For Hire

| | Steam | Xbox |
|---|---|---|
| Location | `%USERPROFILE%\AppData\LocalLow\Fumi Games\MOUSE\Save\` and `\Local\` (per PC) | one container `MouseContainer`, all files flat |
| Game saves | `save<N>.rsf`, `checkpoint<N>.rsf`, `auto.rsf` | same |
| Profile | `profile.rsf` (+ `_backup`): JSON with the Continue pointer (`a`/`b`), settings, bindings, achievement counters (`f`) and collection progress (`g`) | same |
| Machine settings | `local-profile.rsf` (+ `_backup`), copied with `--all` | same |

A Unity game; files are identical across stores and carry no account ID. The
game saves are replaced as a set (so two playthroughs never mix); the profile is
merged: the target keeps its settings and achievement counters and only takes
the Continue pointer. Chapter-select downloads bundle one set per chapter;
point `import` at the chapter's folder (the one holding `Save` and `Local`).

## Achievements and imported saves

Converting never stops achievements from unlocking: they are awarded by the
game and Xbox/Steam when events happen, and no save format here carries an
account ID or an "achievements disabled" flag. What an imported save changes
is what is left to do. Story, chapter and ending achievements unlock only for
the parts played after the save point; stat or collection achievements may pop
the next time the game re-checks them, depending on the game. SILENT HILL 2
keeps its achievement progress in its own file (`UcaSave`), which is not
copied by default.

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
