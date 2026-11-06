# PII De-identification Pipeline

A Linux pipeline (Bash + Python) that de-identifies a large public research email
dataset: batching, detection and redaction of names, emails and phone numbers,
an independent leak check, a human review queue, and an Excel operations tracker.

**Status:** in progress. Day 1 (data intake and profiling) done.

## Data
The [Enron Email Dataset](https://www.cs.cmu.edu/~enron/) (CMU CALO Project, May 2015 version),
a standard public research corpus of about 500K emails from about 150 users.
Raw data, outputs, and anything containing personal information are never committed (see `.gitignore`).

## Run (inside Ubuntu / WSL, not on /mnt/c)
```bash
bin/setup.sh          # download, verify checksum, unpack
bin/profile_data.sh   # counts, duplicates, folder sizes
```
