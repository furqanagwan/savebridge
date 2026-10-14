# Community saves

Saves shared by players, ready to load on Steam or Xbox PC with savebridge.
Each one says who made it, which platform it came from, which game version it
was made on, and where it has been confirmed to load.

```
saves/<game>/<platform>/<save>/
    save.zip     the save, in savebridge's platform-neutral form
    save.json    who, what, which version, where it was tested
```

`<platform>` is where the save was made: `steam`, `xbox-pc`, `xbox-series`,
`ps3`, `ps4` or `ps5`. The game ids are the ones `python -m savebridge games`
lists.

## Using a save

In the app: open the game and pick **Community saves**. On the command line:

```powershell
python -m savebridge community list witcher3
python -m savebridge community get witcher3/steam/<save>
python -m savebridge import witcher3 "<the save.zip it printed>" --to xbox
```

Importing previews the change, backs up your own saves first and verifies the
result, like any other import. Imported saves are added next to yours where the
game allows it.

## Sharing a save

1. Fork this repository and clone your fork.
2. Package the save. Use your own saves (`--from steam` or `--from xbox`), or
   give the save files or folder:

   ```powershell
   python -m savebridge submit witcher3 --from steam --only ManualSave_... `
       --title "NG+ ready, all armour sets" --author yourname --platform steam `
       --game-version 4.04 --tested-on steam `
       --description "Main story and both expansions done; ready for New Game+."
   ```

   This creates `saves/<game>/<platform>/<save>/`. It refuses saves that seem to
   contain personal data (see below).
3. Commit that folder (only that folder) and open a pull request. The checks run
   automatically; a maintainer reviews and merges.

Write a useful description: what is finished, what is still left to do, and
which achievements the save can still give (story achievements only unlock for
what is played after the save point).

## Rules

- Share only saves you made, or have the creator's permission to share.
- No saves edited to unlock paid content, or for use in online or competitive
  modes.
- One playthrough per submission (several slots of it are fine). 50 MB at most.
- The save must load: say where you tested it (`--tested-on`). Untested saves
  are labelled as such.

## Privacy

Saves can carry account IDs or user names. `submit` scans the save for your
SteamID, Xbox user ID and Windows user name (in any encoding), and for any
readable SteamID, Xbox user ID, email address or Windows user-folder path, and
refuses to package it if it finds one. The same scan runs on every pull
request. Some formats are compressed or encrypted, so the scan can't see
everything: only submit saves you are comfortable publishing. The author name
you give is published with the save.

## Testing and versions

`tested` in save.json lists where a save was confirmed to load, by whom and on
which game version. A newer game version usually loads older saves, but not
the other way round, so pick a save made on your version or older.
