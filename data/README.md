# Amazon Redshift unload landing folder

`dt=YYYYMMDD/` partitions delivered by the Amazon Redshift dataset-export
destination (redshift/redshift/dataset-export-destination.json), or written locally
by `redshift/generate_mock_unload.py`: JSON Lines `part-*.json` files, `manifest`
and `_manifest.json`. The backend mounts this folder read-only at
`/data/redshift-unload` and loads the newest complete partition on startup
and whenever a newer one appears.
