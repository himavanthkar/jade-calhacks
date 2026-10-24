# data-archive

The whole `data/` folder, compressed: 21,444 files, 1.3 GB on disk, 272.8 MB here. Almost all of it is
`data/sec/GIS`, General Mills' SEC filings since 1996; the rest is `answer_key.json`,
`program_terms_truth.json` and two Part B verification workbooks.

`data/` itself stays git-ignored. Git stores this folder instead:

| File | What it is |
|---|---|
| `data.tar.gz.part-000` … | `data/` as one gzip-compressed tar, split into parts under GitHub's 100 MB file limit |
| `SHA256SUMS` | a checksum per part; unpacking refuses a corrupt or partly downloaded part |
| `MANIFEST` | the size and path of every file packed, so the hooks can tell when `data/` changed |

## Once per clone

```sh
python3 scripts/data_archive.py setup
```

This turns on the repo's hooks (`git config core.hooksPath .githooks`) and unpacks the archive into
`data/`. Git never runs a repository's hooks until someone opts in like this, so it is the one manual step.

## After that

| You do | The hooks do |
|---|---|
| `git pull`, `git checkout`, `git rebase` | unpack the archive into `data/` if it changed (skipped when `data/` already matches) |
| `git commit` with a changed `data/` | re-pack `data/` and add the new parts to the same commit |
| `git push` | refuse if `data/` changed since it was last packed |

`python3 scripts/data_archive.py status` says whether `data/` matches the archive; `pack` and
`unpack --force` run the two halves by hand. The change check compares file sizes and paths, so an
edit that keeps a file's size is only picked up by running `pack` yourself.

Every re-pack adds a new copy of the archive (about 270 MB) to the repository's history, so re-pack only
when the data really changed.
