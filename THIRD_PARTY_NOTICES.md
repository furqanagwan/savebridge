# Third-party notices

## ooz (optional external executable)

Halo checkpoint decompression invokes [powzix/ooz](https://github.com/powzix/ooz)
as a separate CLI process. Copyright (C) 2016, Powzix; licensed under
GNU GPL version 3 or later. Its source code is not incorporated into the
Python package. `native/build_ooz.ps1` builds revision
`05038060aa68f9187ae9923b2388ca8db40e58d1` and retains its source in the
reported temporary directory, with an added `sys/stat.h` include for MSVC.
If distributing this optional executable, provide its corresponding source,
build instructions, notices, and the [GPL license](https://www.gnu.org/licenses/gpl-3.0.html).

## MandarinJuice

`savebridge/dsss.py` and `native/dsss_find.c` port the Capcom RE Engine DSSS
save encryption from [MandarinJuice](https://github.com/mi5hmash/MandarinJuice)
by mi5hmash, and `savebridge/games/re_engine.py` uses the per-game seed and ID
variant from its game profiles.

```
MIT License

Copyright (c) 2026 Michał Gębicki

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## XboxAuthNet

The app (`app/`) signs in to Xbox Live with [XboxAuthNet](https://github.com/AlphaBs/XboxAuthNet)
(MIT), the library Xbox Achievement Unlocker also uses for its OAuth login.
