# How Xbox PC saves work: research notes

What converting 17 games between Steam and the Xbox PC app has shown about
how Xbox PC (Game Pass / Microsoft Store) games store saves, how that differs
from Steam, and what it takes to move a save across. The first half covers
general findings; the second half is a per-game reference.

Contents

1. [Where Xbox PC saves live](#1-where-xbox-pc-saves-live)
2. [The WGS format](#2-the-wgs-format)
3. [Cloud sync: rules learned the hard way](#3-cloud-sync-rules-learned-the-hard-way)
4. [How games map files to containers](#4-how-games-map-files-to-containers)
5. [How Steam and Xbox save bytes differ](#5-how-steam-and-xbox-save-bytes-differ)
6. [Account binding](#6-account-binding)
7. [Progress kept outside the save](#7-progress-kept-outside-the-save)
8. [Achievements: title-managed and event-based](#8-achievements-title-managed-and-event-based)
9. [Reading Xbox profile, games and achievements](#9-reading-xbox-profile-games-and-achievements)
10. [Capcom RE Engine (DSSS) encryption](#10-capcom-re-engine-dsss-encryption)
11. [Other practical findings](#11-other-practical-findings)
12. [Per-game reference](#12-per-game-reference)
13. [Hard cases](#13-hard-cases)

---

## 1. Where Xbox PC saves live

Almost every Xbox PC game saves through the GDK's **XGameSave** API, which
Windows stores in the game's package folder:

```
%LOCALAPPDATA%\Packages\<package family name>\SystemAppData\wgs\<XUID>_<SCID>\
    containers.index
    <folder GUID>\container.<N>
    <folder GUID>\<blob GUID>
```

- `<XUID>` is the Xbox user ID as 16 hex digits and `<SCID>` the title's
  service configuration ID. One folder per Xbox profile that has played. An
  account can have **more than one** folder for a game (an old, empty cloud ID
  next to the live one); pick the one whose index lists the game's containers.
- The folder only appears after the game has been started once on that
  profile, so every Xbox write needs "launch the game once" first.

Variations seen:

| Where | Games | Notes |
|---|---|---|
| `wgs` containers only | most | the standard case |
| `wgs` **plus** `SystemAppData\xgs\<XUID>_<id>\<container>\<blob>` | Black Ops II, FF7 Rebirth | "XGameSaveFiles": plain-file copies the game reads first. Both copies must be written, or the game loads the stale one. |
| `wgs` **plus** a copy in the install folder | CoD: Ghosts (`<drive>:\XboxGames\<game>\Content\players2\<decimal XUID>\`) | the game keeps its own mirror and prefers it |
| plain files, no `wgs` | Destroy All Humans! (2020) | the Xbox build writes the same per-PC folder as Steam, so no cloud sync |

## 2. The WGS format

**`containers.index`** (version 14): a header (version, entry count, a
FILETIME of the last change, flags) and one entry per container:

| Field | Meaning |
|---|---|
| name | UTF-16, also repeated as a display name |
| ETag | the cloud's version tag; empty for a container never uploaded |
| container number `N` | which `container.N` manifest is current (bumped on every write) |
| state | 1 synced, 2 modified locally, 3 deleted, 5 created locally |
| folder GUID | the directory holding the manifest and blobs |
| FILETIME | last write |
| reserved | per-game value, usually 0 (FF7 Remake uses 1) |
| size | total bytes of the container's blobs |

The header flags include a **FullyUploaded** bit (bit 1).

**`container.N`** (the manifest) lists the container's blobs: a small header,
then one 160-byte entry per blob:

```
128 bytes  blob name, UTF-16, NUL padded
 16 bytes  cloud GUID  - the blob's identity in the cloud copy
 16 bytes  disk GUID   - the file name of the blob in the folder
```

A blob's bytes are the file named after its disk GUID. Blob names are the
game's own (e.g. `Data`, `lobby`, `SaveData001Slot`).

## 3. Cloud sync: rules learned the hard way

The Xbox app uploads changes while a game is running, based on the index
state and the manifest GUIDs. Writing them wrong does not corrupt anything
locally, but the app gets stuck on "Synchronizing" forever.

- **A new blob gets cloud GUID = all zeros.** The service assigns one on upload.
- **A replaced blob keeps its previous cloud GUID.** Only the disk GUID (and file) changes.
- **Never set cloud GUID = disk GUID.** Doing that stalled sync indefinitely
  (METAL GEAR SOLID Δ). Rewriting the manifests with the rules above fixed it immediately.
- **Never invent an ETag.** Keep the existing one; leave it empty for new containers.
- Mark new containers **5 (created)** and changed ones **2 (modified)**, move
  the index FILETIME forward, and clear **FullyUploaded**.
- Write a new `container.N+1` and blob files, then switch the index, then
  delete the superseded files. Never edit a live blob in place.
- **The upload happens only while the game runs.** Launch online, wait at the
  menu, quit from the menu. If the game's process hangs on exit (seen with
  Onimusha), the upload waits until the process is ended in Task Manager.
- If the Xbox app reports a conflict, keep the copy on this PC.

Restoring a backup follows the same rules: savebridge writes the backed-up
saves back as new versions instead of unzipping old files over new ones, which
would bring back stale ETags.

## 4. How games map files to containers

| Pattern | Games |
|---|---|
| One container per save file, one blob `Data` (the Unreal Engine default) | Samson, Dispatch, Beast of Reincarnation, SILENT HILL 2, FF7 Remake / Rebirth, METAL GEAR SOLID Δ (container names add a random suffix) |
| One container per save, several blobs (one per file) | Crimson Desert (`slot<N>`: `lobby`, `save`), CONTROL (`slot-<N>`: one blob per save-point part), The Blood of Dawnwalker (`Data`, `Meta`, `SaveIcon`) |
| One container, every file a blob | Cuphead (`GameSaveContainer`), MOUSE: P.I. For Hire (`MouseContainer`), Black Ops II (`players`), Ghosts (`Gamerprofile_gdk`) |
| Container named after the Steam sub-folder | Kingdom Come: Deliverance II (`saves/playline<N>`, one blob per `.whs`) |
| Container and blob both named after the file | Capcom RE Engine (`data001Slot.bin` → container and blob `SaveData001Slot`) |

When several saves share a container, writing one must keep the other blobs
(Cuphead's settings and controller map, MOUSE's profile).

## 5. How Steam and Xbox save bytes differ

| Difference | Games |
|---|---|
| **None**: identical bytes | 13 of 17 games |
| Compression | FF7 Remake (Xbox: `bilz` header + zlib; Steam: raw), FF7 Rebirth (Xbox: bare zlib) |
| Checksum trailer version | METAL GEAR SOLID Δ (CityHash64 trailer, obfuscated differently: Steam v2, Xbox v1) |
| Encrypted per account | Capcom RE Engine (DSSS, section 10) |
| Different encryption key | Resonance: A Plague Tale Legacy (section 13) |

Encryption that is **not** tied to the account copies byte for byte:
Crimson Desert's ChaCha20 + HMAC key is a constant mixed with the header version.

## 6. Account binding

| Binding | Games | Effect |
|---|---|---|
| None | most | copy as is |
| Owner recorded, not enforced | Black Ops II (`savegame.foo` stores a SteamID or XUID at offset 64) | loads on another account unchanged (verified) |
| Encryption keyed to the account | Capcom RE Engine | must be decrypted with the writer's ID and re-encrypted with the reader's |

## 7. Progress kept outside the save

A downloaded "100% save" often lacks state that the game keeps elsewhere:

| Game | Where | What |
|---|---|---|
| CoD: Ghosts | profile `settings_s.zip.iw6`, field `0x29` | mission select unlocks (a 50-digit string, one digit per level) |
| Destroy All Humans! | `SaveOptions.sav` | unlocked skins (`m_profileUnlockTags`) |
| SILENT HILL 2 | `UcaSave` | achievement progress counters |
| MOUSE: P.I. For Hire | `profile.rsf` | Continue pointer, achievement counters, collection progress |
| CONTROL | `preferences` | Continue pointer |

savebridge merges these so the target keeps its own settings and counters and
takes only what the imported save needs (the Continue pointer, unlock tags).

## 8. Achievements: title-managed and event-based

Converting a save never blocks achievements: no save format seen carries an
"achievements disabled" flag. What decides whether an imported save unlocks
anything is **how the game awards achievements**, which Xbox exposes per
achievement. [Xbox Achievement Unlocker](https://github.com/Fumo-Unlockers/Xbox-Achievement-Unlocker)
documents the two kinds:

- **Title-managed** (most modern games): the game itself tells Xbox Live
  "achievement X unlocked" when its own logic decides so. Many games re-check
  their conditions when a save loads or a chapter ends, so a converted save can
  unlock story or collection achievements soon after it's loaded.
- **Event-based** (older Xbox Live, e.g. Halo MCC, Forza Horizon 3, Gears 4):
  the game only sends *events* ("mission completed", "car added"), and Xbox
  Live's servers count them into stats and unlock the achievement when a stat
  crosses a threshold. Progress lives on the server, not in the save, so loading
  a finished save doesn't replay the events: those achievements unlock only by
  doing the thing again.

The achievements API shows which kind a game uses: an achievement's
`progression.requirements[0].id` is the zero GUID
(`00000000-0000-0000-0000-000000000000`) for title-managed achievements and a
stat ID for event-based ones.

In practice, with an imported save: story, chapter and ending achievements
unlock only for what is played **after** the save point, and counters (kills,
collectibles) may or may not pop, depending on whether the game re-checks and
on whether the counter lives in the save, a separate file or on the server.

## 9. Reading Xbox profile, games and achievements

The app reads the signed-in user's own Xbox data, read-only, with the normal
Microsoft sign-in (the "OAuth login" route of Xbox Achievement Unlocker, via
the XboxAuthNet library):

1. Microsoft account OAuth in a browser window (client ID of the Xbox app,
   `000000004424da1f`, scope `service::user.auth.xboxlive.com::MBI_SSL`).
2. A device token, then **SISU** authorization for the relying party
   `http://xboxlive.com`, which returns the XSTS token and the user's XUID and
   user hash.
3. Requests carry `Authorization: XBL3.0 x=<userhash>;<token>`:

| Data | Endpoint |
|---|---|
| Gamertag, gamerscore, picture | `profile.xboxlive.com/users/me/profile/settings?settings=Gamertag,Gamerscore,GameDisplayPicRaw` |
| Played titles with achievement totals | `titlehub.xboxlive.com/users/xuid(<xuid>)/titles/titleHistory/decoration/Achievement,detail,scid` |
| Achievements of one title | `achievements.xboxlive.com/users/xuid(<xuid>)/achievements?titleId=<id>&maxItems=1000` |

XAU's default route instead reads the token out of the running Xbox app's
memory; savebridge doesn't do that. It also never writes achievements.

## 10. Capcom RE Engine (DSSS) encryption

Onimusha: Way of the Sword, and other recent Capcom games (Resident Evil
Requiem, Monster Hunter Wilds, Dragon's Dogma 2, PRAGMATA...), wrap every save
in a `DSSS` file that only the writing account can open. The format and
algorithm come from [MandarinJuice](https://github.com/mi5hmash/MandarinJuice);
savebridge's Python port (`savebridge/dsss.py`) was checked against it byte
for byte in both directions.

```
header   'DSSS', u32 2, u32 flavor (0x10 plain, 0x18 deflate inside), u32 0
slices   528-byte slice header + 1..8 x 16 KiB of data, repeated
footer   128 random bytes, u64 plaintext length, u32 Murmur3-32 of the file
```

- A per-game 64-bit **seed** and the owner's **account ID** run a SplitMix64
  stream. It picks the slice sizes, generates each slice's AES-128 key and OFB
  IV, and XOR-masks the slice headers.
- Each slice header holds the AES key again as four products
  `personal_seed x key_part`, where `personal_seed = (G^(id mod Q) mod P)^20 mod P`
  (ElGamal-style, with fixed 256-bit `P`, `Q`, `G`), plus a CityHash64 of the
  first slice's plaintext and a length check.
- The account ID is a Steam-style 32-bit number, turned into 64 bits by one of
  four per-game "variants" (Onimusha: variant 1, `0xFFFFFFFF00000000 | ~id`).
- On **Steam** it is the SteamID's account number. On **Xbox** it is a
  different per-account number Capcom assigns. It is not the XUID or any
  obvious hash of it (360 hash/encoding combinations of the XUID were tried).

Recovering an unknown ID: the first 64 bytes of every slice header are a fixed
value, so the masked copy in the file reveals the first 8 bytes of the ID's
SplitMix64 stream. Testing one ID costs 24 SplitMix64 steps; all 2^32 take
about 6 seconds on a desktop CPU in native code (`native/dsss_find.c`), and
would take days in pure Python. savebridge therefore:

1. tries IDs it already knows (the Steam folder the file came from, Steam
   accounts on this PC, IDs found before, kept locally in
   `%LOCALAPPDATA%\savebridge\dsss-ids.json`);
2. otherwise searches all 2^32 with the native helper;
3. for an Xbox target, recovers the account's ID from **its own existing save**
   of the game, which is why the Xbox version must have saved once.

Converting a downloaded Steam save to Xbox: find the uploader's ID, decrypt,
find the Xbox account's ID, encrypt, sign. The result loaded in game and
uploaded to the cloud.

REFramework (praydog) was checked for anything useful: it is a runtime mod
framework with engine type dumps, and contains nothing about save files or
DSSS encryption.

## 11. Other practical findings

- **Store executables can't be read.** `C:\Program Files\WindowsApps` and
  `<drive>:\XboxGames\<game>\Content` deny reads to normal users, so an Xbox
  build can't be disassembled offline (this is what blocks Resonance).
- **Long paths.** `wgs` paths under a long user or package name pass 260
  characters; every file operation uses `\\?\` paths, and backups are zip
  files (copying trees failed on long paths).
- **High-DPI.** Older Xbox PC ports (Black Ops II) aren't DPI-aware and top out
  at 1280x720 on a 4K screen at 300% scaling. Setting "Override high DPI scaling:
  Application" (`~ HIGHDPIAWARE` in
  `HKCU\Software\Microsoft\Windows NT\CurrentVersion\AppCompatFlags\Layers`)
  for the game's executables makes native resolution available.
- **Downloads bundle several save sets.** Importing refuses a folder that
  mixes save sets, since mixing their files corrupts saves.
- **Unreal GVAS**: UE5 headers add a second package version when the save-game
  version is 3 or more, and from UE 5.4 each property tag also carries a
  type-parameter count and a flags byte.

## 12. Per-game reference

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
| Location | `%LOCALAPPDATA%\MGSDelta\Saved\SaveGames\<SteamID64>\` | `wgs` |
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
| `DevAutoSave_<N>.sav` | `BFGCore.BFGSaveGame` | progress |
| `SaveOptions.sav` | `BFGCore.BFGSaveOptions` | settings, key bindings, unlocked skins, last used save |

Importing the options merges them: your settings stay, unlocked skins
(`m_profileUnlockTags`) are combined, and "last used save" points at the newest
imported save. Destroy All Humans! 2 – Reprobed saves use the same classes on a
newer engine and hang the 2020 game, so they are refused (engine version and
world names).

### CONTROL Resonant

Every file is a Remedy RMDB blob with the same bytes on both stores:
`'RMDB'`, `u32 2`, `u32 2`, `u32 crc32(bytes 16..end)`, payload. A slot is a set
of save points (`auto-N`, `key-<id>`, `return`), each split into `-header`
(Unix time at offset 20 plus the area path), `-player`, `-persi-global` and
`-bundle-container`.

| | Steam | Xbox |
|---|---|---|
| Location | `Steam\userdata\<account id>\3669870\remote\` | container per slot, one blob per file |
| Slot 0 | `slot-0_<point>-<part>` | container `slot-0`, blobs `<point>-<part>` |
| Preferences | `preferences_data` (settings), `preferences_savegame` (Continue pointer) | container `preferences`, blobs `data`, `savegame` |
| Achievements | (Steam's own) | container `achievements`, left alone |

A slot is replaced as a whole. A Play Anywhere title: Xbox writes sync to
consoles on the same account.

### Samson: A Tyndalston Story

Unreal Engine 5.7, identical GVAS files, no checksum, no account ID.
`SaveGame.sav`, `SaveGame_Checkpoint_StartOfDay.sav` and `SaveGameManifest.sav`
travel together; `SharedGameSettings.sav` and `EnhancedInputUserSettings.sav`
are settings. One save slot.

### The Blood of Dawnwalker

Each save is three files, same bytes on both stores: `<Name>.sav` (Rebel
Wolves' chunked `DSAV` game state, blob `Data`), `<Name>.meta` (JSON for the
load menu, blob `Meta`) and `<Name>.png` (blob `SaveIcon`). The `.sav` doesn't
record its slot, so moving a save rewrites only the meta's
`SaveName`/`Type`/`TypeString`. The Xbox-only `RebelSettings` is left alone.

### Call of Duty: Black Ops II (campaign)

| | Steam | Xbox |
|---|---|---|
| Location | `<Steam library>\steamapps\common\Call of Duty Black Ops II\players\` | container `players`, one blob per file, plus the `xgs` copy |
| Progress | `savegame.svg` (level name at offset 32), `savegame.foo` | same |
| Settings | `bindings_sp.bdg`, `user_sp.cgp`, `user_common.cgp` | same |

`savegame.foo` records its owner at offset 64 behind an unidentified 4-byte
checksum; the game still loads it on another account. Multiplayer and zombies
keep progress on Activision's servers, not in local files.

### Call of Duty: Ghosts (campaign)

| | Steam | Xbox |
|---|---|---|
| Location | `<Steam library>\steamapps\common\Call of Duty Ghosts\players2\` | container `Gamerprofile_gdk`, plus the install-folder mirror |
| Continue point | `savegame.svg` (IW6, version `0x47`) | same, plus `save\internal/snd_restart.svg` (removed when the save is replaced) |
| Profile | `settings_s.zip.iw6` | same |

The profile is a `SEMV` file: 12-byte header, then 43 fields of `id, type,
value` (type 1 bool, 2 byte, 4 int32, 6 string), no checksum. Field `0x29` is
one digit per campaign level; non-zero unlocks the mission in mission select
(verified). Field `0x2a` is another per-mission string, not the Rorke Files;
where the Rorke Files are recorded is still unknown.

### Kingdom Come: Deliverance II

Steam: `%USERPROFILE%\Saved Games\kingdomcome2\saves\playline<N>\*.whs` (per
PC). Xbox: container `saves/playline<N>`, one blob per file. A `.whs` is
`0xFFFFFFFF`, a length, an XML `<C_SaveGameDescription>` (id, type, time,
level, build, DLCs and mods), then compressed data. No account ID and no
playline number inside. Downloads can hold hundreds of saves, more than the
cloud quota comfortably takes, hence `--files newest`.

### Crimson Desert

Steam: `%LOCALAPPDATA%\Pearl Abyss\CD\save\<SteamID64>\slot<N>\lobby.save`,
`save.save`; Xbox: container `slot<N>`, blobs `lobby`, `save`. Both files are
`SAVE` v2: a 0x80-byte header (flags, sizes, ChaCha20 nonce, HMAC-SHA256) and an
LZ4-compressed, ChaCha20-encrypted body. The key is a constant mixed with the
header version ([pycrimson](https://github.com/LukeFZ/pycrimson)), so files copy
byte for byte. Slots 0-2 are manual, 100 and up automatic.

### SILENT HILL 2 (2024)

One `.sav` per container. `SaveGameData_<N>` uses a `VASb` wrapper (header
length, `0xDEAD`, the `SHSaveGame` class, a save-point GUID and the map name,
then a zlib-compressed UE 5.1 GVAS body). New Game+ and ending setup live in
each save; `PersistentData` records the last slot; `UcaSave` holds achievement
progress.

### FINAL FANTASY VII REMAKE INTERGRADE and REBIRTH

| | Steam | Xbox |
|---|---|---|
| Location | `Documents\My Games\FINAL FANTASY VII REMAKE\Steam\<SteamID64>\` | container per save, blob `Data` |
| Saves | `ff7remake<NNN>.sav`, `ff7remakeplus<NNN>.sav` (INTERmission), `ff7remakecommon.sav` | same names |
| Format | raw save (9,434,752 bytes per slot) | `bilz`, u32 compressed size, u32 raw size, 8 zero bytes, zlib stream |

REBIRTH uses the same raw format and naming (`ff7rebirth<NNN>`), but its Xbox
blob is a bare zlib stream with no `bilz` header, and it also reads the `xgs` copy.

### Dispatch

One UE 4.27 `.sav` per container. `SaveSlot<N>` (+ `_BACKUP`) is the save and
`Index` (+ `_BACKUP`) records each slot's latest scene, so they travel together.

### Beast of Reincarnation

One UE 5.4 `.sav` per container, each an `AibouSaveDataContainer` (a GVAS shell
around a compressed payload). `borSaveDataNormal_<N>` and
`borSaveDataNormal_AutoSave_<N>` are saves; `borSaveDataMeta` (+ backups) is one
index for all of them, so slots always travel with the index.

### Cuphead

Steam: `%APPDATA%\Cuphead\cuphead_player_data_v1_slot_<N>.sav` (per PC); Xbox:
container `GameSaveContainer`, blobs without `.sav`, next to
`cuphead_settings_data_v1` and a Rewired controller map (`r2|…`). Plain JSON, no
slot number inside.

### MOUSE: P.I. For Hire

Unity. Steam: `%USERPROFILE%\AppData\LocalLow\Fumi Games\MOUSE\Save\` and
`\Local\`; Xbox: container `MouseContainer`, all files flat. Game saves
(`save<N>.rsf`, `checkpoint<N>.rsf`, `auto.rsf`) are replaced as a set;
`profile.rsf` is merged (only the Continue pointer changes).

### Onimusha: Way of the Sword

Steam: `Steam\userdata\<account id>\2638890\remote\win64_save\data<X>.bin`;
Xbox: container and blob `SaveData<X>` (e.g. `SaveData001Slot`). DSSS
encrypted (section 10), seed `0xA235A0818E21A7A6`, ID variant 1.

## 13. Hard cases

### Halo: Campaign Evolved (Steam → Xbox verified in game)

Steam app [2806050](https://store.steampowered.com/app/2806050/Halo_Campaign_Evolved/).
Installed Xbox `MicrosoftGame.config` identifies package
`Microsoft.198377053870B_8wekyb3d8bbwe`, title `7C27BAE7`, executable
`HaloCampaignEvolved.exe`. Live WGS contains `CoreSave_0`, `CoreSave_1`,
and `Progress`, each with a single `Data` blob. No xgs mirror was present.
The armory DLC package is not the save package.

`Progress.sav` is GVAS (`BlamProgressLocalPlayerSaveGame`) with mission
completion/insertion-point tags, skulls and terminals. Checkpoints contain:

- `HALOCEVO`, u32 version 0, u32 uncompressed size;
- u64 `222222229E2A83C1`, u64 chunk size 131072, byte compressor 2;
- u64 total compressed size, u64 total raw size;
- one `(u64 compressed, u64 raw)` pair per chunk, followed by Oodle Kraken streams.

Decompressed checkpoints are GVAS `BlamSaveSlotSaveGame`, containing metadata
and binary Blam game state. Slot 0 references the main campaign; slot 1 the
additional Operation: METEORITE campaign. They are not interchangeable slots.
`PerPlayerXuidMapping` is a UE5 UInt64 property, but its value does not equal
the local XUID. All four inspected solo checkpoints contain seven copies of
their profile's same opaque value: one metadata value and six inside the
game state. The converter learns the destination value from existing
checkpoints and replaces all seven copies, refusing conflicting mappings or
other copy counts. This is an observed layout, not a general co-op parser.

The downloaded Steam sample is CU2. Xbox checkpoints are CU2/CU3; Xbox
progress is CU4. Engine 5.5.4/package versions agree; custom-version counts
differ. Headers and versions are preserved, with no guessed build migration.
The user confirmed the imported CU2 saves loaded in the current Xbox PC
build on 2026-10-02. Xbox → Steam loading has not been confirmed in game.

Decompression uses the separately built GPL ooz CLI, pinned by
`native/build_ooz.ps1`; encoding uses valid raw Oodle blocks (`CC 06`) with
rebuilt archive sizes. No proprietary Oodle DLL is redistributed. The
Steam SaveGames destination is provisional: there is no installed Steam
save tree on this PC to confirm account subfolders. Download import and
the Xbox WGS mapping have been checked against actual samples.

Real save files stay outside version control. Tests use synthetic GVAS,
raw Oodle blocks and WGS stores. Synthetic round trips cover both directions;
successful Steam → Xbox loading was separately confirmed by the user.

### Resonance: A Plague Tale Legacy: blocked

Every file (`slot00`, `slot01`, `settings`, `inputprofile`) is encrypted in
full on both stores.

| | Steam | Xbox |
|---|---|---|
| Storage | `Steam\userdata\<account>\2713000\remote\` | container per file, blob `data` |
| Cipher | AES-128-CBC, zero IV, PKCS#7; key = first 16 bytes of SHA-1(`asobo` + 24 × `3` + `asobo`) | 16-byte blocks, **unknown key** |

- The Xbox key is not the Steam key, nor any of about 4,600 variations tried
  (the XUID in several encodings, platform names, other fillers in the template,
  SHA-1/MD5/SHA-256) against a known plaintext (`inputprofile` must start `<?xml`).
- The Xbox executable can't be read (section 11).
- The only known method, [documented here](https://github.com/berkay496/ResonanceAPlagueTaleLegacySteamToGamePassSaveConvert),
  is live memory injection: break in the running game's save routine with a
  debugger and swap in the decrypted Steam save. It depends on the exact build
  and needs administrator rights, so savebridge doesn't automate it.

What would unblock it: the Xbox key or its derivation.
